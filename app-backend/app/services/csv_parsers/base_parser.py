import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, TextIOWrapper
from typing import Any, Dict, List, Optional, Tuple

from core_cash_shared import (
    VALIDATION_EMPTY_FILE,
    VALIDATION_FILE_TOO_LARGE,
    VALIDATION_MISSING_COLUMN,
    VALIDATION_UNSUPPORTED_FORMAT,
)


class ValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class BaseParser:
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    ALLOWED_MIME_TYPES = {"text/csv", "application/csv"}

    @staticmethod
    def validate_file_format(filename: str, content_type: Optional[str] = None) -> None:
        if not filename.lower().endswith(".csv"):
            raise ValidationError(
                VALIDATION_UNSUPPORTED_FORMAT,
                f"Only CSV files are supported. Received: {filename}",
            )
        if content_type and content_type.lower() not in BaseParser.ALLOWED_MIME_TYPES:
            raise ValidationError(
                VALIDATION_UNSUPPORTED_FORMAT,
                f"Only CSV files are supported. Received MIME type: {content_type}",
            )

    @staticmethod
    def validate_file_size(file_content: bytes) -> None:
        if len(file_content) > BaseParser.MAX_FILE_SIZE:
            size_mb = len(file_content) / (1024 * 1024)
            raise ValidationError(
                VALIDATION_FILE_TOO_LARGE,
                f"File exceeds 10 MB limit. Received: {size_mb:.1f} MB",
            )

    @staticmethod
    def read_csv(content: bytes) -> Tuple[List[str], List[Dict[str, str]]]:
        text_content = TextIOWrapper(BytesIO(content), encoding="utf-8")
        reader = csv.DictReader(text_content)
        if not reader.fieldnames:
            raise ValidationError(
                VALIDATION_EMPTY_FILE,
                "CSV file contains no data rows",
            )
        rows = list(reader)
        if not rows:
            raise ValidationError(
                VALIDATION_EMPTY_FILE,
                "CSV file contains no data rows",
            )
        return reader.fieldnames or [], rows

    @staticmethod
    def resolve_column(
        fieldnames: List[str],
        logical_name: str,
        aliases: Dict[str, List[str]],
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        if logical_name in column_mapping:
            mapped = column_mapping[logical_name]
            if mapped in fieldnames:
                return mapped
            for fn in fieldnames:
                if fn.lower() == mapped.lower():
                    return fn
            return None

        acceptable_names = aliases.get(logical_name, [])
        for name in acceptable_names:
            if name in fieldnames:
                return name
            for fn in fieldnames:
                if fn.lower() == name.lower():
                    return fn
        return None

    @staticmethod
    def resolve_columns(
        fieldnames: List[str],
        required_columns: Dict[str, List[str]],
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, str], List[str]]:
        column_mapping = column_mapping or {}
        resolved = {}
        missing = []
        for logical_name, aliases in required_columns.items():
            col = BaseParser.resolve_column(fieldnames, logical_name, required_columns, column_mapping)
            if col:
                resolved[logical_name] = col
            else:
                missing.append(logical_name)
        if missing:
            raise ValidationError(
                VALIDATION_MISSING_COLUMN,
                f"Required columns not found: {', '.join(missing)}",
            )
        return resolved, missing

    @staticmethod
    def parse_date(value: str) -> Optional[datetime]:
        if not value or not value.strip():
            return None
        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]:
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def parse_decimal(value: str) -> Optional[Decimal]:
        if not value or not value.strip():
            return None
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def parse_float(value: str) -> Optional[float]:
        if not value or not value.strip():
            return None
        try:
            return float(value.strip())
        except (ValueError, TypeError):
            return None
