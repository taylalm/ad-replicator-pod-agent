"""Agents sometimes write their progress lines in the user's language ("BƯỚC 8/11: assemble - hoàn tất",
"步骤 10/11 ..."). The site reads "STEP n/11: name - started|done|failed|skipped": translate the localized forms."""
import re

_WORD = re.compile(r"(?:BƯỚC|Bước|bước|BUOC|步骤|步驟|ステップ)\s*(\d+)\s*/\s*(\d+)\s*[:：]?")
_STATUS = [
    ("done", r"hoàn tất|hoàn thành|đã xong|xong|已完成|完成|完了"),
    ("started", r"bắt đầu|đã bắt đầu|đang bắt đầu|开始|開始|已开始"),
    ("failed", r"thất bại|lỗi|失败|失敗"),
    ("skipped", r"bỏ qua|跳过|跳過|スキップ"),
]
_HEAD = r"(STEP\s+\d+\s*/\s*\d+\s*:[^\n]*?\s+-\s+)"


def normalize(text: str) -> str:
    if not text or not (_WORD.search(text) or "STEP" in text):
        return text
    text = _WORD.sub(r"STEP \1/\2:", text)
    for word, alts in _STATUS:
        text = re.sub(_HEAD + rf"(?:{alts})", rf"\g<1>{word}", text)
    return text
