"""Workbook transformations that do not read or mutate workflow state."""

import os
import shutil

import pandas as pd

from .processor import PackingBoxProcessor

def _load_modified_packing_result(file_path: str) -> pd.DataFrame:
    """读取并校验修正版拼箱结果"""
    sheet_name = '拼箱计算结果'
    try:
        merge_summary = pd.read_excel(file_path, sheet_name=sheet_name)
    except ValueError as exc:
        if sheet_name in str(exc):
            raise ValueError(f"缺少工作表：{sheet_name}") from exc
        raise

    required_columns = [
        'SKU',
        '发货数量',
        '单份数量',
        '小组名称',
        '单箱重量',
        '单箱理论长',
        '单箱理论宽',
        '单箱理论高',
    ]
    missing_columns = [col for col in required_columns if col not in merge_summary.columns]
    if missing_columns:
        raise ValueError(f"缺少必要列：{', '.join(missing_columns)}")

    merge_summary = merge_summary.copy()
    fill_columns = ['小组名称', '单箱重量', '单箱理论长', '单箱理论宽', '单箱理论高']
    for col in fill_columns:
        merge_summary[col] = merge_summary[col].ffill()

    sku_series = merge_summary['SKU'].dropna().map(lambda value: str(value).strip())
    merge_summary = merge_summary.loc[sku_series[sku_series != ''].index].copy()
    if merge_summary.empty:
        raise ValueError("拼箱计算结果中没有可用的SKU行")

    # 写出时同组「实际箱数」是合并单元格；新拆出的组也可能漏填。
    # 不能按列 ffill：单独装箱共用小组名但箱数不同。空值按 发货数量/单份数量 反推。
    if '实际箱数' in merge_summary.columns:
        actual = pd.to_numeric(merge_summary['实际箱数'], errors='coerce')
        missing = actual.isna()
        if missing.any():
            inferred = pd.to_numeric(
                merge_summary.apply(PackingBoxProcessor._infer_actual_box_count, axis=1),
                errors='coerce',
            )
            inferred = inferred.where(inferred > 0)
            actual = actual.where(~missing, inferred)
        merge_summary['实际箱数'] = actual

    numeric_columns = ['发货数量', '单份数量', '单箱重量', '单箱理论长', '单箱理论宽', '单箱理论高']
    if '箱数' in merge_summary.columns:
        numeric_columns.append('箱数')
    if '实际箱数' in merge_summary.columns:
        numeric_columns.append('实际箱数')
    invalid_columns = []
    for col in numeric_columns:
        converted = pd.to_numeric(merge_summary[col], errors='coerce')
        if converted.isna().any():
            invalid_columns.append(col)
        else:
            merge_summary[col] = converted
    if invalid_columns:
        raise ValueError(f"以下列存在非数字或空值：{', '.join(invalid_columns)}")

    return merge_summary


def _fill_amazon_packaging(packing_result_path: str, amazon_file_path: str, final_result_path: str) -> None:
    summary = pd.read_excel(packing_result_path, sheet_name='拼箱计算结果')
    cols = ['小组名称', '单箱重量', '单箱理论长', '单箱理论高', '单箱理论宽']
    summary[cols] = summary[cols].ffill()
    processor = PackingBoxProcessor(input_file_path=packing_result_path, output_file_path=packing_result_path)
    processor.insert_data_to_amazon_packaging(amazon_file_path, summary)
    if os.path.abspath(amazon_file_path) != os.path.abspath(final_result_path):
        shutil.copy2(amazon_file_path, final_result_path)


def _create_amazon_template_v2(packing_result_path: str, template_path: str, template_source: str) -> None:
    summary = pd.read_excel(packing_result_path, sheet_name='拼箱计算结果')
    for col in ['小组名称', '单箱重量', '单箱理论长', '单箱理论高', '单箱理论宽']:
        if col in summary.columns:
            summary[col] = summary[col].ffill()
    processor = PackingBoxProcessor(input_file_path=packing_result_path, output_file_path=packing_result_path)
    processor.create_amazon_template(template_path, summary, template_source=template_source)
