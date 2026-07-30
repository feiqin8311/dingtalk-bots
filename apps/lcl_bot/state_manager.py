# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
状态管理器 - 管理钉钉机器人工作流状态
"""

from datetime import datetime
import json
import os
from typing import Any, Dict, Optional

from . import config


class WorkflowState:
    """工作流状态枚举"""
    IDLE = 'IDLE'  # 空闲状态
    LOGISTICS_UPLOADED = 'LOGISTICS_UPLOADED'  # 物流已上传，待确认
    WAIT_OPS_SELECT = 'WAIT_OPS_SELECT'  # 物流已确认，待选择运营
    LOGISTICS_CONFIRMED = 'LOGISTICS_CONFIRMED'  # 已转发运营，待运营上传
    OPERATION_UPLOADED = 'OPERATION_UPLOADED'  # 运营已上传，处理中
    WAIT_DELETE_CONFIRMATION = 'WAIT_DELETE_CONFIRMATION'  # 等待运营确认是否删除发货单
    WAIT_SHIPMENT_NUMBERS = 'WAIT_SHIPMENT_NUMBERS'  # 等待运营输入领星发货单号
    WAIT_CUSTOMS_INFO = 'WAIT_CUSTOMS_INFO'  # 等待物流补全清关资料
    WAIT_LOGISTICS_FILES = 'WAIT_LOGISTICS_FILES'  # 等待物流上传发货单/报关资料Excel


class StateManager:
    """状态管理器 - 管理工作流状态转换和持久化"""
    
    def __init__(self, state_file_path: str = None):
        """初始化状态管理器"""
        self.state_file_path = state_file_path or config.STATE_FILE_PATH
        self.state = self._load_state()
    
    def _load_state(self) -> Dict[str, Any]:
        """从文件加载状态"""
        default_state = self._get_default_state()
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, 'r', encoding='utf-8') as f:
                    loaded_state = json.load(f)
                    for key, value in default_state.items():
                        loaded_state.setdefault(key, value)
                    return loaded_state
            except Exception as e:
                print(f"⚠️  加载状态文件失败: {e}，使用默认状态")
        
        return default_state
    
    def _get_default_state(self) -> Dict[str, Any]:
        """获取默认状态"""
        return {
            'status': WorkflowState.IDLE,
            'logistics_file_path': None,
            'packing_result_path': None,
            'amazon_template_path': None,
            'shipping_numbers': None,
            'lingxing_shipment_numbers': None,
            'logistics_user_id': None,
            'operation_user_id': None,
            'conversation_id': None,
            'workflow_folder_path': None,
            'registry_code': None,
            'shared_folder_path': None,
            'pending_customs_shipments': None,
            'pending_customs_reason': None,
            'lingxing_partial_results': None,
            'lock_stock_partial_results': None,
            'logistics_files_received': [],
            'logistics_files_expected': None,
            'customs_prev_status': None,
            'created_at': None,
            'updated_at': None
        }
    
    def _save_state(self):
        """保存状态到文件"""
        try:
            self.state['updated_at'] = datetime.now().isoformat()
            with open(self.state_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ 保存状态文件失败: {e}")
    
    def get_status(self) -> str:
        """获取当前状态"""
        return self.state.get('status', WorkflowState.IDLE)
    
    def is_idle(self) -> bool:
        """检查是否处于空闲状态"""
        return self.get_status() == WorkflowState.IDLE
    
    def is_waiting_for_confirmation(self) -> bool:
        """检查是否正在等待物流确认"""
        return self.get_status() == WorkflowState.LOGISTICS_UPLOADED

    def is_waiting_for_ops_select(self) -> bool:
        """物流已确认，等待选择要转发的运营"""
        return self.get_status() == WorkflowState.WAIT_OPS_SELECT
    
    def is_waiting_for_operation(self) -> bool:
        """检查是否正在等待运营上传"""
        return self.get_status() == WorkflowState.LOGISTICS_CONFIRMED

    def set_waiting_for_ops_select(self) -> None:
        if not self.is_waiting_for_confirmation():
            raise ValueError(f"当前状态为 {self.get_status()}，无法进入选运营")
        self.state["status"] = WorkflowState.WAIT_OPS_SELECT
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.WAIT_OPS_SELECT}")

    def is_waiting_for_delete_confirmation(self) -> bool:
        """检查是否等待运营确认删除发货单"""
        return self.get_status() == WorkflowState.WAIT_DELETE_CONFIRMATION

    def is_waiting_for_shipment_numbers(self) -> bool:
        """检查是否等待运营输入发货单号"""
        return self.get_status() == WorkflowState.WAIT_SHIPMENT_NUMBERS

    def is_waiting_for_customs_info(self) -> bool:
        """检查是否等待物流补全清关资料"""
        return self.get_status() == WorkflowState.WAIT_CUSTOMS_INFO

    def is_waiting_for_logistics_files(self) -> bool:
        """检查是否等待物流上传发货单/报关资料文件"""
        return self.get_status() == WorkflowState.WAIT_LOGISTICS_FILES
    
    def set_logistics_uploaded(self, logistics_user_id: str, logistics_file_path: str, 
                               packing_result_path: str, conversation_id: str,
                               amazon_template_path: Optional[str] = None,
                               shipping_numbers: Optional[str] = None,
                               workflow_folder_path: Optional[str] = None,
                               registry_code: Optional[str] = None,
                               shared_folder_path: Optional[str] = None):
        """设置物流已上传状态"""
        if not self.is_idle():
            raise ValueError(f"当前状态为 {self.get_status()}，无法上传新文件。请先完成当前流程。")
        
        self.state.update({
            'status': WorkflowState.LOGISTICS_UPLOADED,
            'logistics_user_id': logistics_user_id,
            'logistics_file_path': logistics_file_path,
            'packing_result_path': packing_result_path,
            'amazon_template_path': amazon_template_path,
            'shipping_numbers': shipping_numbers,
            'conversation_id': conversation_id,
            'workflow_folder_path': workflow_folder_path,
            'registry_code': registry_code,
            'shared_folder_path': shared_folder_path,
            'created_at': datetime.now().isoformat()
        })
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.LOGISTICS_UPLOADED}")
    
    def set_logistics_confirmed(self, operation_user_ids: list):
        """设置已转发运营（从选运营或旧确认路径进入）"""
        if not (self.is_waiting_for_confirmation() or self.is_waiting_for_ops_select()):
            raise ValueError(f"当前状态为 {self.get_status()}，无法执行确认/转发操作")

        self.state["status"] = WorkflowState.LOGISTICS_CONFIRMED
        self.state["operation_user_ids"] = operation_user_ids
        if operation_user_ids:
            self.state["operation_user_id"] = operation_user_ids[0]
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.LOGISTICS_CONFIRMED}")
    
    def set_operation_uploaded(self, operation_user_id: str, amazon_file_path: str):
        """设置运营已上传状态"""
        if not self.is_waiting_for_operation():
            raise ValueError(f"当前状态为 {self.get_status()}，运营暂时无法上传文件")
        
        self.state['status'] = WorkflowState.OPERATION_UPLOADED
        self.state['operation_user_id'] = operation_user_id
        self.state['amazon_file_path'] = amazon_file_path
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.OPERATION_UPLOADED}")

    def set_waiting_for_delete_confirmation(self, operation_user_id: Optional[str] = None):
        """设置等待删除确认状态"""
        self.state['status'] = WorkflowState.WAIT_DELETE_CONFIRMATION
        if operation_user_id:
            self.state['operation_user_id'] = operation_user_id
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.WAIT_DELETE_CONFIRMATION}")

    def set_waiting_for_shipment_numbers(self, operation_user_id: Optional[str] = None):
        """设置等待输入发货单号状态"""
        self.state['status'] = WorkflowState.WAIT_SHIPMENT_NUMBERS
        if operation_user_id:
            self.state['operation_user_id'] = operation_user_id
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.WAIT_SHIPMENT_NUMBERS}")

    def set_waiting_for_customs_info(self, pending_shipments: list, reason: str,
                                     partial_results: Optional[list] = None,
                                     lock_stock_results: Optional[dict] = None):
        """设置等待物流补全清关资料状态"""
        self.state['customs_prev_status'] = self.state.get('status')
        self.state['status'] = WorkflowState.WAIT_CUSTOMS_INFO
        self.state['pending_customs_shipments'] = pending_shipments
        self.state['pending_customs_reason'] = reason
        self.state['lingxing_partial_results'] = partial_results or []
        self.state['lock_stock_partial_results'] = lock_stock_results or {"success": [], "failed": []}
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.WAIT_CUSTOMS_INFO}")

    def clear_customs_waiting(self, restore_status: Optional[str] = None):
        """清理等待清关补全状态，恢复之前状态"""
        prev_status = restore_status or self.state.get('customs_prev_status') or WorkflowState.WAIT_SHIPMENT_NUMBERS
        self.state['status'] = prev_status
        self.state['pending_customs_shipments'] = None
        self.state['pending_customs_reason'] = None
        self.state['lingxing_partial_results'] = None
        self.state['lock_stock_partial_results'] = None
        self.state['customs_prev_status'] = None
        self._save_state()

    def get_pending_customs_shipments(self) -> Optional[list]:
        """获取待处理清关的发货单列表"""
        return self.state.get('pending_customs_shipments')

    def get_pending_customs_reason(self) -> Optional[str]:
        """获取清关缺失原因"""
        return self.state.get('pending_customs_reason')

    def get_lingxing_partial_results(self) -> Optional[list]:
        """获取领星处理部分结果"""
        return self.state.get('lingxing_partial_results')

    def get_lock_stock_partial_results(self) -> Optional[dict]:
        """获取库存分配部分结果"""
        return self.state.get('lock_stock_partial_results')

    def set_waiting_for_logistics_files(self, expected_count: int = 2):
        """设置等待物流上传Excel文件状态"""
        self.state['status'] = WorkflowState.WAIT_LOGISTICS_FILES
        self.state['logistics_files_received'] = []
        self.state['logistics_files_expected'] = expected_count
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.WAIT_LOGISTICS_FILES}")

    def add_logistics_received_file(self, file_path: str):
        """记录物流上传的文件"""
        files = self.state.get('logistics_files_received') or []
        files.append(file_path)
        self.state['logistics_files_received'] = files
        self._save_state()

    def get_logistics_received_files(self) -> list:
        """获取物流已上传文件列表"""
        return self.state.get('logistics_files_received') or []

    def get_logistics_files_expected(self) -> Optional[int]:
        """获取物流期望上传文件数量"""
        return self.state.get('logistics_files_expected')

    def set_lingxing_shipment_numbers(self, numbers: list):
        """存储领星发货单号列表"""
        self.state['lingxing_shipment_numbers'] = numbers
        self._save_state()

    def get_lingxing_shipment_numbers(self) -> Optional[list]:
        """获取领星发货单号列表"""
        return self.state.get('lingxing_shipment_numbers')
    
    def reset(self):
        """重置状态为空闲"""
        self.state = self._get_default_state()
        self._save_state()
        print(f"✅ 状态已重置: {WorkflowState.IDLE}")
    
    def get_logistics_user_id(self) -> Optional[str]:
        """获取物流人员ID"""
        return self.state.get('logistics_user_id')

    def get_operation_user_id(self) -> Optional[str]:
        """获取运营人员ID"""
        return self.state.get('operation_user_id')
    
    def get_packing_result_path(self) -> Optional[str]:
        """获取拼箱结果文件路径"""
        return self.state.get('packing_result_path')
    
    def get_amazon_file_path(self) -> Optional[str]:
        """获取Amazon文件路径"""
        return self.state.get('amazon_file_path')
    
    def get_logistics_file_path(self) -> Optional[str]:
        """获取物流原始文件路径"""
        return self.state.get('logistics_file_path')
    
    def get_amazon_template_path(self) -> Optional[str]:
        """获取Amazon模板文件路径"""
        return self.state.get('amazon_template_path')

    def get_shipping_numbers(self) -> Optional[str]:
        """获取发货单号串"""
        return self.state.get('shipping_numbers')
    
    def get_conversation_id(self) -> Optional[str]:
        """获取会话ID"""
        return self.state.get('conversation_id')
    
    def get_workflow_folder_path(self) -> Optional[str]:
        """获取当前流程的文件夹路径"""
        return self.state.get('workflow_folder_path')

    def update_workflow_folder_path(self, folder_path: Optional[str]):
        """更新流程文件夹路径"""
        self.state['workflow_folder_path'] = folder_path
        self._save_state()

    def update_packing_result(self, packing_result_path: str,
                              amazon_template_path: Optional[str] = None):
        """更新当前流程使用的拼箱结果和Amazon模板路径"""
        self.state['packing_result_path'] = packing_result_path
        if amazon_template_path is not None:
            self.state['amazon_template_path'] = amazon_template_path
        self._save_state()
    
    def get_full_state(self) -> Dict[str, Any]:
        """获取完整状态信息"""
        return self.state.copy()

    def inject_data(self, data: Dict[str, Any]):
        """注入/覆盖状态中的关键上下文数据"""
        if not isinstance(data, dict):
            raise ValueError("inject_data 需要 dict 类型参数")
        self.state.update(data)
        self._save_state()

    def force_jump(self, stage_alias: str) -> str:
        """根据里程碑别名强制跳转状态"""
        alias = (stage_alias or "").strip()
        alias_map = {
            "分5仓拼箱": WorkflowState.WAIT_DELETE_CONFIRMATION,
            "拼箱": WorkflowState.WAIT_DELETE_CONFIRMATION,
            "领星编辑": WorkflowState.WAIT_SHIPMENT_NUMBERS,
            "领星": WorkflowState.WAIT_SHIPMENT_NUMBERS,
            "生成清关资料": WorkflowState.WAIT_LOGISTICS_FILES,
            "清关资料": WorkflowState.WAIT_LOGISTICS_FILES,
        }
        if alias not in alias_map:
            raise ValueError(f"未知里程碑阶段: {alias}")
        self.state['status'] = alias_map[alias]
        self._save_state()
        return self.state['status']
    
    def rollback(self, previous_status: str):
        """回滚到指定状态"""
        valid_statuses = [
            WorkflowState.IDLE,
            WorkflowState.LOGISTICS_UPLOADED,
            WorkflowState.WAIT_OPS_SELECT,
            WorkflowState.LOGISTICS_CONFIRMED,
            WorkflowState.OPERATION_UPLOADED,
            WorkflowState.WAIT_DELETE_CONFIRMATION,
            WorkflowState.WAIT_SHIPMENT_NUMBERS,
            WorkflowState.WAIT_CUSTOMS_INFO,
            WorkflowState.WAIT_LOGISTICS_FILES,
        ]
        
        if previous_status not in valid_statuses:
            raise ValueError(f"无效的状态: {previous_status}")
        
        self.state['status'] = previous_status
        self._save_state()
        print(f"✅ 状态已回滚: {previous_status}")


# 单例模式：全局状态管理器实例
_state_manager_instance = None


def get_state_manager() -> StateManager:
    """获取全局状态管理器实例"""
    global _state_manager_instance
    if _state_manager_instance is None:
        _state_manager_instance = StateManager()
    return _state_manager_instance
