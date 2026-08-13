# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
状态管理器 - 管理钉钉机器人工作流状态
"""

from datetime import datetime
import json
import os
import re
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
            'logistics_user_id': None,
            'operation_user_id': None,
            'conversation_id': None,
            'workflow_folder_path': None,
            # 运营侧：一单一单 + 队列（与物流上传会话解耦）
            'ops_active': {},   # ops_id -> job dict
            'ops_queue': {},    # ops_id -> [job dict, ...]
            # 物流会话阶段（与运营 status 解耦，转发后可 IDLE 接下一单）
            'logistics_phase': 'IDLE',  # IDLE | UPLOADED | WAIT_OPS_SELECT
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

    def logistics_phase(self) -> str:
        return self.state.get("logistics_phase") or (
            "IDLE" if self.is_idle() else "BUSY"
        )

    def can_logistics_upload(self) -> bool:
        """物流是否可上传新发货单（不依赖运营是否在处理）。"""
        phase = self.state.get("logistics_phase")
        if phase is not None:
            return phase == "IDLE"
        return self.is_idle()
    
    def is_waiting_for_confirmation(self) -> bool:
        """检查是否正在等待物流确认"""
        if self.state.get("logistics_phase") == "UPLOADED":
            return True
        return self.get_status() == WorkflowState.LOGISTICS_UPLOADED

    def is_waiting_for_ops_select(self) -> bool:
        """物流已确认，等待选择要转发的运营"""
        if self.state.get("logistics_phase") == "WAIT_OPS_SELECT":
            return True
        return self.get_status() == WorkflowState.WAIT_OPS_SELECT
    
    def is_waiting_for_operation(self, ops_user_id: Optional[str] = None) -> bool:
        """检查是否正在等待运营上传（可按运营 id 查当前单）。"""
        if self.get_status() == WorkflowState.LOGISTICS_CONFIRMED:
            if not ops_user_id:
                return True
            active = (self.state.get("ops_active") or {}).get(str(ops_user_id))
            if active:
                return True
            op_ids = self.state.get("operation_user_ids") or []
            if self.state.get("operation_user_id") == ops_user_id:
                return True
            return ops_user_id in op_ids
        # 物流已释放后，仅看 ops_active
        active_map = self.state.get("ops_active") or {}
        if ops_user_id:
            job = active_map.get(str(ops_user_id))
            return bool(job and job.get("status") == "WAIT_AMAZON")
        return any(
            j.get("status") == "WAIT_AMAZON" for j in active_map.values() if isinstance(j, dict)
        )

    def set_waiting_for_ops_select(self) -> None:
        if not self.is_waiting_for_confirmation():
            raise ValueError(f"当前状态为 {self.get_status()}，无法进入选运营")
        self.state["status"] = WorkflowState.WAIT_OPS_SELECT
        self.state["logistics_phase"] = "WAIT_OPS_SELECT"
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.WAIT_OPS_SELECT}")

    def is_waiting_for_delete_confirmation(self) -> bool:
        """检查是否等待运营确认删除发货单"""
        return self.get_status() == WorkflowState.WAIT_DELETE_CONFIRMATION

    def set_logistics_uploaded(self, logistics_user_id: str, logistics_file_path: str, 
                               packing_result_path: str, conversation_id: str,
                               amazon_template_path: Optional[str] = None,
                               shipping_numbers: Optional[str] = None,
                               workflow_folder_path: Optional[str] = None,
                               shop: Optional[str] = None,
                               shop_full: Optional[str] = None,
                               country: Optional[str] = None,
                               transport_method: Optional[str] = None):
        """设置物流已上传状态"""
        if not self.can_logistics_upload():
            raise ValueError(
                f"当前物流会话未结束（phase={self.state.get('logistics_phase')} status={self.get_status()}），"
                "请先完成确认/转发或重置后再上传。"
            )
        
        self.state.update({
            'status': WorkflowState.LOGISTICS_UPLOADED,
            'logistics_phase': 'UPLOADED',
            'logistics_user_id': logistics_user_id,
            'logistics_file_path': logistics_file_path,
            'packing_result_path': packing_result_path,
            'amazon_template_path': amazon_template_path,
            'shipping_numbers': shipping_numbers,
            'conversation_id': conversation_id,
            'workflow_folder_path': workflow_folder_path,
            'shop': shop,
            'shop_full': shop_full,
            'country': country,
            'transport_method': transport_method,
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

    def snapshot_current_job(self) -> Dict[str, Any]:
        """从当前物流会话快照一单，供运营 active/queue 使用。"""
        return {
            "logistics_file_path": self.state.get("logistics_file_path"),
            "packing_result_path": self.state.get("packing_result_path"),
            "amazon_template_path": self.state.get("amazon_template_path"),
            "shipping_numbers": self.state.get("shipping_numbers"),
            "logistics_user_id": self.state.get("logistics_user_id"),
            "conversation_id": self.state.get("conversation_id"),
            "workflow_folder_path": self.state.get("workflow_folder_path"),
            "shop": self.state.get("shop"),
            "shop_full": self.state.get("shop_full"),
            "country": self.state.get("country"),
            "transport_method": self.state.get("transport_method"),
            "status": "WAIT_AMAZON",
            "created_at": datetime.now().isoformat(),
        }

    def ops_is_busy(self, ops_id: str) -> bool:
        active = (self.state.get("ops_active") or {}).get(str(ops_id))
        return bool(active)

    @staticmethod
    def shipment_keys_from_job(job: Optional[Dict[str, Any]]) -> frozenset:
        if not job:
            return frozenset()
        keys: set[str] = set()
        for sn in job.get("shipping_numbers") or []:
            if sn:
                keys.add(str(sn).strip().upper())
        for field in ("packing_result_path", "logistics_file_path"):
            path = job.get(field)
            if path:
                for m in re.finditer(r"\bSP[0-9A-Za-z]+\b", str(path), flags=re.IGNORECASE):
                    keys.add(m.group(0).upper())
        return frozenset(keys)

    @staticmethod
    def shipment_keys_overlap(a, b) -> bool:
        return bool(a and b and (set(a) & set(b)))

    def drop_queue_jobs_overlapping(self, ops_id: str, keys) -> list:
        """Drop queued jobs sharing shipment keys. Returns dropped packing basenames."""
        keys = frozenset(keys or [])
        if not keys:
            return []
        ops_id = str(ops_id)
        queue = dict(self.state.get("ops_queue") or {})
        items = list(queue.get(ops_id) or [])
        kept = []
        dropped = []
        for job in items:
            if self.shipment_keys_overlap(keys, self.shipment_keys_from_job(job)):
                path = (job or {}).get("packing_result_path") or ""
                dropped.append(os.path.basename(path) if path else "queued")
            else:
                kept.append(job)
        if len(kept) != len(items):
            if kept:
                queue[ops_id] = kept
            else:
                queue.pop(ops_id, None)
            self.state["ops_queue"] = queue
            self._save_state()
        return dropped

    def pop_next_queued_job(self, ops_id: str):
        """弹出该运营队列第一单；无则 None。"""
        ops_id = str(ops_id)
        queue = dict(self.state.get("ops_queue") or {})
        items = list(queue.get(ops_id) or [])
        if not items:
            return None
        job = items.pop(0)
        if items:
            queue[ops_id] = items
        else:
            queue.pop(ops_id, None)
        self.state["ops_queue"] = queue
        self._save_state()
        return job

    def enqueue_ops_job(self, ops_id: str, job: Dict[str, Any]) -> int:
        """运营忙碌时入队，返回排队位次（1-based）。"""
        ops_id = str(ops_id)
        queue = dict(self.state.get("ops_queue") or {})
        items = list(queue.get(ops_id) or [])
        items.append(job)
        queue[ops_id] = items
        self.state["ops_queue"] = queue
        self._save_state()
        return len(items)

    def activate_ops_job(self, ops_id: str, job: Dict[str, Any]) -> None:
        """设为运营当前处理单，并绑定到全局字段供现有 handler 使用。"""
        ops_id = str(ops_id)
        job = dict(job)
        job["status"] = job.get("status") or "WAIT_AMAZON"
        active = dict(self.state.get("ops_active") or {})
        active[ops_id] = job
        self.state["ops_active"] = active
        self.state["operation_user_id"] = ops_id
        self.state["operation_user_ids"] = [ops_id]
        # 注入路径，兼容 get_packing_result_path 等
        for key in (
            "logistics_file_path",
            "packing_result_path",
            "amazon_template_path",
            "shipping_numbers",
            "logistics_user_id",
            "conversation_id",
            "workflow_folder_path",
            "shop",
            "shop_full",
            "country",
            "transport_method",
        ):
            if job.get(key) is not None:
                self.state[key] = job.get(key)
        self.state["status"] = WorkflowState.LOGISTICS_CONFIRMED
        self._save_state()

    def release_logistics_session(self) -> None:
        """物流转发后释放：可立刻上传下一单；保留 ops_active / ops_queue。"""
        ops_active = dict(self.state.get("ops_active") or {})
        ops_queue = dict(self.state.get("ops_queue") or {})
        # 物流 phase 置 IDLE，允许下一单；运营路径字段从 active 回填一份兼容
        self.state["logistics_phase"] = "IDLE"
        if ops_active:
            # 任取一个 active 填全局路径，供未改全的 get_* 兼容
            pick_id = next(iter(ops_active.keys()))
            job = ops_active[pick_id]
            self.state["operation_user_id"] = pick_id
            self.state["operation_user_ids"] = [pick_id]
            for key in (
                "logistics_file_path",
                "packing_result_path",
                "amazon_template_path",
                "shipping_numbers",
                "logistics_user_id",
                "conversation_id",
                "workflow_folder_path",
                "shop",
                "shop_full",
                "country",
                "transport_method",
            ):
                if job.get(key) is not None:
                    self.state[key] = job.get(key)
            self.state["status"] = WorkflowState.LOGISTICS_CONFIRMED
        else:
            self.state["status"] = WorkflowState.IDLE
            self.state["operation_user_id"] = None
            self.state["operation_user_ids"] = []
        self.state["ops_active"] = ops_active
        self.state["ops_queue"] = ops_queue
        self._save_state()
        print("✅ 物流会话已释放，运营队列保留")

    def finish_ops_job_and_promote(self, ops_id: str) -> Optional[Dict[str, Any]]:
        """结束运营当前单；若有排队则激活下一单并返回 job，否则 None。"""
        ops_id = str(ops_id)
        active = dict(self.state.get("ops_active") or {})
        active.pop(ops_id, None)
        self.state["ops_active"] = active
        queue = dict(self.state.get("ops_queue") or {})
        items = list(queue.get(ops_id) or [])
        next_job = None
        if items:
            next_job = items.pop(0)
            if items:
                queue[ops_id] = items
            else:
                queue.pop(ops_id, None)
        self.state["ops_queue"] = queue
        self._save_state()
        if next_job:
            self.activate_ops_job(ops_id, next_job)
            return next_job
        # 无下一单：若其它运营也无 active，可 idle
        if not active:
            self.state["status"] = WorkflowState.IDLE
            self.state["operation_user_id"] = None
            self.state["operation_user_ids"] = []
            self._save_state()
        return None

    def get_ops_queue_length(self, ops_id: str) -> int:
        return len((self.state.get("ops_queue") or {}).get(str(ops_id)) or [])

    def bind_ops_job_to_state(self, ops_id: str) -> bool:
        """把指定运营的 active job 写回全局路径字段。"""
        job = (self.state.get("ops_active") or {}).get(str(ops_id))
        if not job:
            return False
        self.activate_ops_job(ops_id, job)
        return True
    
    def set_operation_uploaded(self, operation_user_id: str, amazon_file_path: str):
        """设置运营已上传状态"""
        if not self.is_waiting_for_operation(operation_user_id):
            raise ValueError(f"当前状态为 {self.get_status()}，运营暂时无法上传文件")
        
        self.state['status'] = WorkflowState.OPERATION_UPLOADED
        self.state['operation_user_id'] = operation_user_id
        self.state['amazon_file_path'] = amazon_file_path
        # 同步 active job
        active = dict(self.state.get("ops_active") or {})
        job = dict(active.get(str(operation_user_id)) or {})
        if job:
            job["status"] = "OPERATION_UPLOADED"
            job["amazon_file_path"] = amazon_file_path
            active[str(operation_user_id)] = job
            self.state["ops_active"] = active
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.OPERATION_UPLOADED}")

    def set_waiting_for_delete_confirmation(self, operation_user_id: Optional[str] = None):
        """设置等待删除确认状态"""
        self.state['status'] = WorkflowState.WAIT_DELETE_CONFIRMATION
        if operation_user_id:
            self.state['operation_user_id'] = operation_user_id
        self._save_state()
        print(f"✅ 状态已更新: {WorkflowState.WAIT_DELETE_CONFIRMATION}")

    def reset_logistics_only(self) -> None:
        """物流【重置】专用：只清物流会话，完整保留所有运营 active/queue。"""
        ops_active = dict(self.state.get("ops_active") or {})
        ops_queue = dict(self.state.get("ops_queue") or {})
        self.state = self._get_default_state()
        self.state["ops_active"] = ops_active
        self.state["ops_queue"] = ops_queue
        self.state["logistics_phase"] = "IDLE"
        if ops_active:
            pick_id = next(iter(ops_active.keys()))
            # 不设 needs_push，避免重复推送进行中的单
            self.activate_ops_job(pick_id, ops_active[pick_id])
        else:
            self._save_state()
        print(f"✅ 物流会话已重置(运营流程不受影响) active={len(ops_active)} queue={len(ops_queue)}")

    def reset(self):
        """结束当前运营单并重置；保留其他运营的 active/queue，物流可接单。"""
        ops_active = dict(self.state.get("ops_active") or {})
        ops_queue = dict(self.state.get("ops_queue") or {})
        finishing = self.state.get("operation_user_id")
        next_job = None
        if finishing:
            ops_active.pop(str(finishing), None)
            items = list(ops_queue.get(str(finishing)) or [])
            if items:
                next_job = items.pop(0)
                if items:
                    ops_queue[str(finishing)] = items
                else:
                    ops_queue.pop(str(finishing), None)
        self.state = self._get_default_state()
        self.state["ops_active"] = ops_active
        self.state["ops_queue"] = ops_queue
        self.state["logistics_phase"] = "IDLE"
        if next_job and finishing:
            next_job = dict(next_job)
            next_job["needs_push"] = True
            self.activate_ops_job(str(finishing), next_job)
            print(f"✅ 状态重置并提升队列: ops={finishing}")
        elif ops_active:
            pick_id = next(iter(ops_active.keys()))
            self.activate_ops_job(pick_id, ops_active[pick_id])
            print(f"✅ 状态已重置(保留其他ops): active={len(ops_active)}")
        else:
            self._save_state()
            print("✅ 状态已重置: IDLE")
    
    def get_logistics_user_id(self) -> Optional[str]:
        """获取物流人员ID"""
        return self.state.get('logistics_user_id')

    def get_operation_user_id(self) -> Optional[str]:
        """获取运营人员ID"""
        return self.state.get('operation_user_id')
    
    def get_packing_result_path(self, ops_user_id: Optional[str] = None) -> Optional[str]:
        """获取拼箱结果文件路径（运营优先读自己的 active job）。"""
        if ops_user_id:
            job = (self.state.get("ops_active") or {}).get(str(ops_user_id))
            if job and job.get("packing_result_path"):
                return job.get("packing_result_path")
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
