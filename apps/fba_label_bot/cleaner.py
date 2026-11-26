"""清理 FBA 箱唛：删除指定公司名及发货信息。

逻辑来自 FBA箱唛/clean_fba_labels.py，改为纯内存：输入 PDF 字节，输出处理后的 PDF 字节。
依赖 PyMuPDF>=1.24.3。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pymupdf


COMPANIES = (
    'Hangzhou Easy Can Tools Co., Ltd.',
    'Hangzhou Jiangsheng E-Commerce Co., Ltd.',
)
SENDER_LINES = (
    'EZARC Tools',
    'Zhejiang - Hangzhou - 311121',
    'No.1008 Xiangwang Street',
    'Tolesa Tools',
    'Zhejiang - Hangzhou - 310030',
    'Rm. 2-3028, Bld. B, Jiangcun Business CenterNo. 830 Wenyixi',
    'Road',
    '中国',
)
SUFFIX = '-已处理'


@dataclass(frozen=True)
class CleanResult:
    pages: int
    content: Optional[bytes]  # None：没有匹配到待删除文字


def label_rule(text):
    # 只处理已验证的 FBA 文本模板；其他编码或扫描件需另加规则。
    # 直接删除文字指令，避免重写其余绘图指令，让条码和箱号保持原样。
    is_company_line = text.startswith('FBA: ')
    if is_company_line:
        literal = f'({text})'.encode('ascii')
        replacement = b'(FBA:)'
    else:
        encoded = text.encode('utf-16-be')
        literal = b'(' + encoded + b')'
        replacement = b''

    array_item = re.escape(literal)
    if not is_company_line:
        hex_string = encoded.hex().encode('ascii')
        array_item += b'|<' + hex_string + b'>'
    pattern = re.compile(
        re.escape(literal) + rb'\s*Tj\b|\[\s*(?:' + array_item + rb')\s*\]\s*TJ\b',
        re.IGNORECASE,
    )
    return pattern, replacement + b'Tj' if replacement else b''


def clean_pdf_bytes(data: bytes) -> CleanResult:
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        expected_text = []
        stream_updates = {}
        company_lines = tuple(f'FBA: {company}' for company in COMPANIES)
        rules = {text: label_rule(text) for text in (*company_lines, *SENDER_LINES)}
        for page in doc:
            text = page.get_text()
            lines = text.splitlines()
            if '目的地：' in lines and '发货地：' in lines:
                streams = {xref: doc.xref_stream(xref) for xref in page.get_contents()}
                sender_start = lines.index('发货地：') + 1
                # “Road”等地址续行仅在右侧发货信息内匹配。
                sender_lines = lines[sender_start:]
                sender_end = next((i for i, line in enumerate(sender_lines)
                                   if line.startswith('Created:')), len(sender_lines))
                targets = [line for line in SENDER_LINES if line in sender_lines[:sender_end]]
                targets.extend(line for line in company_lines if line in lines[:sender_start])
                for target in targets:
                    pattern, replacement = rules[target]
                    matches = 0
                    for xref, stream in streams.items():
                        streams[xref], count = pattern.subn(replacement, stream)
                        matches += count
                    if matches != 1:
                        raise ValueError(f'第 {page.number + 1} 页无法精确定位 {target!r}')
                    start = sender_start if target in SENDER_LINES else 0
                    index = lines.index(target, start)
                    lines[index] = 'FBA:' if target in company_lines else ''
                if targets:
                    stream_updates.update(streams)
            expected_text.append('\n'.join(lines).split())

        if not stream_updates:
            return CleanResult(pages=len(expected_text), content=None)
        for xref, stream in stream_updates.items():
            doc.update_stream(xref, stream)
        result = doc.tobytes(deflate=True)

    # 重新打开成品，确认每页只移除了指定文字。
    with pymupdf.open(stream=result, filetype='pdf') as checked:
        if len(checked) != len(expected_text):
            raise ValueError('页数核对失败')
        for page, expected in zip(checked, expected_text):
            if page.get_text().split() != expected:
                raise ValueError(f'第 {page.number + 1} 页文字核对失败')

    return CleanResult(pages=len(expected_text), content=result)


def output_file_name(file_name: str) -> str:
    stem = file_name[:-4] if file_name.lower().endswith('.pdf') else file_name
    if stem.endswith(SUFFIX):
        return f'{stem}.pdf'
    return f'{stem}{SUFFIX}.pdf'
