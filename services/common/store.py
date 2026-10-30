"""Tiny key-value store: DynamoDB on AWS, in-memory dict locally.

A table is DynamoDB-backed when its ``<NAME>_TABLE`` env var is set, otherwise it
lives in process memory (good enough for local runs and tests). Numbers are kept
as integers (prices in cents) so DynamoDB ``Decimal`` round-trips cleanly.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from decimal import Decimal
from typing import Any

from common.config import AWS_REGION


class ConditionFailed(Exception):
    """Raised when a conditional update (e.g. stock reservation) is rejected."""


def _plain(value: Any) -> Any:
    """Convert DynamoDB Decimals back into ints/floats, recursively."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _ddb_safe(item: dict) -> dict:
    """DynamoDB rejects Python floats; round-trip them through Decimal."""
    return json.loads(json.dumps(item), parse_float=Decimal)


class Table:
    """A table with a partition key and an optional sort key."""

    def __init__(self, logical_name: str, pk: str, sk: str | None = None):
        self.pk, self.sk = pk, sk
        self.table_name = os.getenv(f"{logical_name.upper()}_TABLE", "")
        self._lock = threading.Lock()
        self._mem: dict[tuple, dict] = {}
        self._ddb = None
        if self.table_name:
            import boto3

            self._ddb = boto3.resource("dynamodb", region_name=AWS_REGION).Table(self.table_name)

    @property
    def backend(self) -> str:
        return "dynamodb" if self._ddb is not None else "memory"

    def _key(self, item: dict) -> tuple:
        return (item[self.pk], item[self.sk]) if self.sk else (item[self.pk],)

    def get(self, pk: str, sk: str | None = None) -> dict | None:
        if self._ddb is not None:
            key = {self.pk: pk, **({self.sk: sk} if self.sk else {})}
            return _plain(self._ddb.get_item(Key=key).get("Item"))
        with self._lock:
            item = self._mem.get((pk, sk) if self.sk else (pk,))
            return copy.deepcopy(item)

    def put(self, item: dict) -> None:
        if self._ddb is not None:
            self._ddb.put_item(Item=_ddb_safe(item))
            return
        with self._lock:
            self._mem[self._key(item)] = copy.deepcopy(item)

    def delete(self, pk: str, sk: str | None = None) -> None:
        if self._ddb is not None:
            self._ddb.delete_item(Key={self.pk: pk, **({self.sk: sk} if self.sk else {})})
            return
        with self._lock:
            self._mem.pop((pk, sk) if self.sk else (pk,), None)

    def scan(self, limit: int | None = None) -> list[dict]:
        if self._ddb is not None:
            kwargs: dict = {"Limit": limit} if limit else {}
            items, resp = [], self._ddb.scan(**kwargs)
            items.extend(resp.get("Items", []))
            while "LastEvaluatedKey" in resp and not limit:
                resp = self._ddb.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
                items.extend(resp.get("Items", []))
            return _plain(items)
        with self._lock:
            items = [copy.deepcopy(v) for v in self._mem.values()]
        return items[:limit] if limit else items

    def query(self, pk: str) -> list[dict]:
        """All items sharing a partition key (e.g. one user's orders)."""
        if self._ddb is not None:
            from boto3.dynamodb.conditions import Key

            resp = self._ddb.query(KeyConditionExpression=Key(self.pk).eq(pk))
            return _plain(resp.get("Items", []))
        with self._lock:
            return [copy.deepcopy(v) for k, v in self._mem.items() if k[0] == pk]

    def add_to_counter(self, pk: str, attr: str, delta: int, floor: int = 0) -> int:
        """Atomically add ``delta`` to a numeric attribute, refusing to go below ``floor``."""
        if self._ddb is not None:
            from botocore.exceptions import ClientError

            try:
                resp = self._ddb.update_item(
                    Key={self.pk: pk},
                    UpdateExpression="SET #a = #a + :d",
                    ConditionExpression="attribute_exists(#a) AND #a >= :min",
                    ExpressionAttributeNames={"#a": attr},
                    ExpressionAttributeValues={":d": delta, ":min": floor - delta},
                    ReturnValues="UPDATED_NEW",
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    raise ConditionFailed(attr) from exc
                raise
            return _plain(resp["Attributes"][attr])
        with self._lock:
            item = self._mem.get((pk,))
            if item is None or item.get(attr, 0) + delta < floor:
                raise ConditionFailed(attr)
            item[attr] = item.get(attr, 0) + delta
            return item[attr]
