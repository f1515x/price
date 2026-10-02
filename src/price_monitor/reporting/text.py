"""Formatting for terminal and Telegram reports."""
import unicodedata

def _display_width(text):
    """返回文本在常见等宽终端中占用的列数。"""
    width = 0
    for char in text:
        if unicodedata.combining(char) or char in ("\ufe0e", "\ufe0f", "\u200d"):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
    return width


def _format_order_detail_lines(order_details):
    """以最长的完整前缀为基准，补空格使所有冒号纵向对齐。"""
    prefixes = [f"{icon}  {label}" for icon, label, _ in order_details]
    baseline_width = max(_display_width(prefix) for prefix in prefixes)

    return [
        f"{prefix}{' ' * (baseline_width - _display_width(prefix))} : {value}"
        for prefix, (_, _, value) in zip(prefixes, order_details)
    ]

