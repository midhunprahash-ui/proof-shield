"""Generate clearly synthetic document scans for the local OCR benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def generate(output_directory: Path) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required; install the local OCR dependencies first"
        ) from error

    output_directory.mkdir(parents=True, exist_ok=True)
    fixtures: list[dict[str, Any]] = []
    definitions = [
        {
            "scenario": "synthetic_scanned_invoice",
            "evidence_type": "INVOICE",
            "content_type": "image/png",
            "filename": "synthetic_invoice.png",
            "title": "SYNTHETIC INVOICE - NOT A REAL TRANSACTION",
            "lines": [
                "Order ID: order_scan_1001",
                "Payment ID: pay_scan_1001",
                "Invoice Amount: INR 1,249.50",
                "Issued At: 2026-08-20T10:30:00Z",
            ],
            "expected": {
                "order_id": "order_scan_1001",
                "payment_id": "pay_scan_1001",
                "amount": "1249.50",
                "issued_at": "2026-08-20T10:30:00Z",
            },
        },
        {
            "scenario": "synthetic_delivery_photo",
            "evidence_type": "DELIVERY_PROOF",
            "content_type": "image/jpeg",
            "filename": "synthetic_delivery.jpg",
            "title": "SYNTHETIC DELIVERY RECORD",
            "lines": [
                "Order ID: order_scan_1002",
                "Payment ID: pay_scan_1002",
                "Delivery Status: delivered",
            ],
            "expected": {
                "order_id": "order_scan_1002",
                "payment_id": "pay_scan_1002",
                "delivery_status": "delivered",
            },
        },
        {
            "scenario": "synthetic_customer_message_scan",
            "evidence_type": "CUSTOMER_COMMUNICATION",
            "content_type": "image/png",
            "filename": "synthetic_customer_message.png",
            "title": "SYNTHETIC CUSTOMER MESSAGE",
            "lines": [
                "Order ID: order_scan_1003",
                "Payment ID: pay_scan_1003",
                "Message: Package received by customer",
                "Acknowledged Delivery: yes",
            ],
            "expected": {
                "order_id": "order_scan_1003",
                "payment_id": "pay_scan_1003",
                "text": "Package received by customer",
                "customer_acknowledged_delivery": True,
            },
        },
    ]

    title_font = _font(ImageFont, 36)
    body_font = _font(ImageFont, 32)
    for definition in definitions:
        image = Image.new("RGB", (1400, 900), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((45, 45, 1355, 855), outline="#19222f", width=4)
        draw.text((90, 90), definition["title"], fill="#111827", font=title_font)
        draw.line((90, 155, 1310, 155), fill="#94a3b8", width=3)
        for index, line in enumerate(definition["lines"]):
            draw.text((110, 220 + index * 110), line, fill="#111827", font=body_font)
        draw.text(
            (110, 760),
            "Synthetic benchmark fixture - no merchant or customer data",
            fill="#64748b",
            font=_font(ImageFont, 22),
        )
        target = output_directory / definition["filename"]
        if definition["content_type"] == "image/jpeg":
            image.save(target, format="JPEG", quality=88)
        else:
            image.save(target, format="PNG")
        fixtures.append(
            {
                "scenario": definition["scenario"],
                "evidence_type": definition["evidence_type"],
                "content_type": definition["content_type"],
                "source_file": definition["filename"],
                "expected": definition["expected"],
            }
        )

    manifest = output_directory / "ocr_cases.jsonl"
    manifest.write_text(
        "\n".join(json.dumps(fixture, sort_keys=True) for fixture in fixtures) + "\n",
        encoding="utf-8",
    )
    return manifest


def _font(image_font: Any, size: int) -> Any:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return image_font.truetype(name, size=size)
        except OSError:
            continue
    return image_font.load_default(size=size)


def main() -> None:
    manifest = generate(Path("data/synthetic/ocr"))
    print(manifest)


if __name__ == "__main__":
    main()
