# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工具函数模块 - 文件上传下载、钉钉API交互等
"""

import json
import os
import shutil
import time
from typing import Optional, Sequence, Tuple, Union

import requests

from . import config


class DingTalkAPI:
    """钉钉API工具类"""
    
    def __init__(self, client_id: str, client_secret: str):
        """初始化钉钉API工具"""
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token = None
        self._token_expires_at = 0
        self._corp_access_token = None
        self._corp_token_expires_at = 0
        self._openid_userid_cache = {}
    
    def cache_openid_userid(self, open_id: Optional[str], user_id: Optional[str]) -> None:
        """缓存openId与userId的映射"""
        if open_id and user_id:
            self._openid_userid_cache[open_id] = user_id
    
    def get_access_token(self, force_refresh: bool = False) -> str:
        """
        获取访问令牌
        
        Args:
            force_refresh: 是否强制刷新token
            
        Returns:
            access_token字符串
        """
        # 如果token还未过期且不强制刷新，则返回缓存的token
        if not force_refresh and self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        
        try:
            url = config.DINGTALK_TOKEN_URL
            payload = {
                "appKey": self.client_id,
                "appSecret": self.client_secret
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            self._access_token = data['accessToken']
            # token有效期7200秒，提前5分钟刷新
            self._token_expires_at = time.time() + 7200 - 300
            
            print(f"✅ 成功获取access_token")
            return self._access_token
            
        except Exception as e:
            print(f"❌ 获取access_token失败: {e}")
            raise
    
    def get_corp_access_token(self, force_refresh: bool = False) -> str:
        """
        获取旧版OAPI access_token（用于企业内部应用主动调用topapi）
        """
        if not force_refresh and self._corp_access_token and time.time() < self._corp_token_expires_at:
            return self._corp_access_token
        
        try:
            params = {
                "appkey": self.client_id,
                "appsecret": self.client_secret
            }
            response = requests.get(config.DINGTALK_CORP_TOKEN_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('errcode') not in (0, None):
                raise Exception(f"{data.get('errmsg')}")
            
            access_token = data.get('access_token')
            if not access_token:
                raise Exception(f"响应中缺少access_token: {data}")
            
            self._corp_access_token = access_token
            expires_in = data.get('expires_in', 7200)
            self._corp_token_expires_at = time.time() + expires_in - 300
            
            print("✅ 成功获取企业内部应用access_token")
            return self._corp_access_token
        except Exception as e:
            print(f"❌ 获取企业内部应用access_token失败: {e}")
            raise
    
    def get_userid_by_openid(self, open_id: str) -> Optional[str]:
        """
        根据openId查询企业内部userid
        """
        if not open_id:
            return None
        
        if open_id in self._openid_userid_cache:
            return self._openid_userid_cache[open_id]
        
        # 先尝试新OpenAPI的批量查询接口（支持LWCP_v1等新格式openId）
        userid = self._get_userid_by_openid_openapi(open_id)
        if userid:
            return userid
        
        # 回退到旧版topapi接口，兼容历史openId
        userid = self._get_userid_by_openid_legacy(open_id)
        if userid:
            return userid
        
        print(f"⚠️ 根据openId({open_id})获取userid失败: 未从任何接口获得结果")
        return None

    def _get_userid_by_openid_openapi(self, open_id: str) -> Optional[str]:
        """使用 contact/users/batchQuery 接口查询userId"""
        try:
            access_token = self.get_access_token()
            url = f"{config.DINGTALK_API_BASE_URL}/v1.0/contact/users/batchQuery"
            headers = {
                'x-acs-dingtalk-access-token': access_token,
                'Content-Type': 'application/json'
            }
            payload = {'openIds': [open_id]}
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json() if response.content else {}
            
            # 新版接口返回 { "users": [ { "userId": "...", "openId": "..." } ] }
            users = data.get('users') or data.get('result') or []
            if isinstance(users, dict):
                users = [users]
            
            for user in users:
                # response字段大小写不固定，做兼容
                result_open_id = user.get('openId') or user.get('openid')
                userid = user.get('userId') or user.get('userid')
                if userid and (not result_open_id or result_open_id == open_id):
                    self.cache_openid_userid(open_id, userid)
                    return userid
            
            # 如果返回了错误码（OpenAPI通常为code/message结构）
            code = data.get('code')
            if code and code != 'OK':
                raise Exception(data.get('message') or data.get('msg') or code)
        except Exception as e:
            print(f"⚠️ 使用contact/users/batchQuery获取openId({open_id})失败: {e}")
        return None

    def _get_userid_by_openid_legacy(self, open_id: str) -> Optional[str]:
        """回退到旧版topapi/user/getbyopenid接口"""
        try:
            access_token = self.get_corp_access_token()
            url = f"{config.DINGTALK_OAPI_BASE_URL}/topapi/user/getbyopenid"
            params = {'access_token': access_token}
            payload = {'openid': open_id}
            
            response = requests.post(url, params=params, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('errcode') not in (0, None):
                raise Exception(data.get('errmsg') or data.get('message') or data)
            
            result = data.get('result') or {}
            userid = result.get('userid')
            if userid:
                self.cache_openid_userid(open_id, userid)
                return userid
        except Exception as e:
            print(f"⚠️ 旧版topapi根据openId({open_id})获取userid失败: {e}")
        return None
    
    def download_file(self, download_code: str, file_name: str, save_dir: str, file_info: dict = None, session_webhook: str = None, robot_code: str = None) -> str:
        """
        下载钉钉文件
        
        Args:
            download_code: 文件下载码
            file_name: 文件名
            save_dir: 保存目录
            file_info: 额外的文件信息（如spaceId, fileId等）
            
        Returns:
            本地文件路径
        """
        try:
            # 获取access_token
            access_token = self.get_access_token()
            
            # 方式1: 尝试使用 downloadCode 直接下载（旧版API）
            print(f"📥 尝试下载文件: {file_name}")
            print(f"🔑 downloadCode前20个字符: {download_code[:20]}...")
            
            # 直接使用downloadCode作为下载链接（某些版本的钉钉）
            # downloadCode可能已经是完整的下载URL或包含了必要的token
            headers = {
                'x-acs-dingtalk-access-token': access_token,
                'User-Agent': 'DingTalk-Bot/1.0'
            }
            
            # 方式-2: 使用 robotCode + downloadCode（正确方式！）
            if robot_code and download_code:
                try:
                    print(f"📡 方式-2: 使用 robotCode + downloadCode 下载")
                    print(f"   robotCode: {robot_code[:20]}...")
                    
                    download_api = f"{config.DINGTALK_API_BASE_URL}/v1.0/robot/messageFiles/download"
                    
                    print(f"📡 发送POST请求到: {download_api}")
                    response = requests.post(
                        download_api,
                        headers=headers,
                        json={
                            'downloadCode': download_code,
                            'robotCode': robot_code
                        },
                        timeout=60
                    )
                    
                    print(f"📡 响应状态: {response.status_code}")
                    
                    if response.status_code == 200:
                        content_type = response.headers.get('Content-Type', '')
                        print(f"📡 Content-Type: {content_type}")
                        print(f"✓ 下载成功，文件大小: {len(response.content)} 字节")
                        
                        # 检查是否是JSON错误响应
                        if 'application/json' in content_type:
                            try:
                                result = response.json()
                                # 可能返回的是下载链接
                                if 'downloadUrl' in result or 'url' in result:
                                    download_url = result.get('downloadUrl') or result.get('url')
                                    print(f"📥 获取到下载链接: {download_url[:50]}...")
                                    file_response = requests.get(download_url, timeout=60, trust_env=False)
                                    file_response.raise_for_status()
                                    file_path = self._save_downloaded_file(file_response.content, file_name, save_dir)
                                    return file_path
                                elif 'errcode' in result and result['errcode'] != 0:
                                    print(f"⚠️ 接口返回错误: {result}")
                                    raise Exception(f"下载失败: {result.get('errmsg', 'Unknown error')}")
                            except Exception as e:
                                print(f"⚠️ JSON解析或处理失败: {e}")
                        else:
                            # 直接是文件内容
                            file_path = self._save_downloaded_file(response.content, file_name, save_dir)
                            return file_path
                    else:
                        print(f"⚠️ 响应内容: {response.text[:200]}")
                except Exception as e:
                    print(f"⚠️ 方式-2失败: {e}")
            
            # 方式-1: 使用 session_webhook 下载（Stream模式专用）
            if session_webhook and download_code:
                try:
                    print(f"📡 方式-1: 使用 session_webhook 下载")
                    print(f"   webhook: {session_webhook[:50]}...")
                    
                    # 使用POST请求，downloadCode放在请求体中
                    print(f"📡 发送POST请求到: {session_webhook}")
                    file_response = requests.post(
                        session_webhook,
                        json={'downloadCode': download_code},
                        headers={'Content-Type': 'application/json'},
                        timeout=60
                    )
                    
                    print(f"📡 响应状态: {file_response.status_code}")
                    
                    # 检查响应内容
                    if file_response.status_code == 200:
                        content_type = file_response.headers.get('Content-Type', '')
                        print(f"📡 Content-Type: {content_type}")
                        print(f"✓ 下载成功，文件大小: {len(file_response.content)} 字节")
                        
                        # 检查是否是JSON错误响应
                        if 'application/json' in content_type:
                            try:
                                error_data = file_response.json()
                                if 'errcode' in error_data and error_data['errcode'] != 0:
                                    print(f"⚠️ 接口返回错误: {error_data}")
                                    raise Exception(f"下载失败: {error_data.get('errmsg', 'Unknown error')}")
                            except:
                                pass
                        
                        # 保存文件
                        file_path = self._save_downloaded_file(file_response.content, file_name, save_dir)
                        return file_path
                    else:
                        print(f"⚠️ 响应内容: {file_response.text[:200]}")
                except Exception as e:
                    print(f"⚠️ 方式-1失败: {e}")
            
            # 方式0: 使用 spaceId 和 fileId 下载（钉钉网盘文件）
            if file_info and file_info.get('spaceId') and file_info.get('fileId'):
                try:
                    space_id = file_info.get('spaceId')
                    file_id = file_info.get('fileId')
                    
                    print(f"📡 方式0: 使用 spaceId={space_id}, fileId={file_id}")
                    
                    # 钉钉网盘文件下载API
                    download_url_api = f"{config.DINGTALK_API_BASE_URL}/v1.0/drive/spaces/{space_id}/files/{file_id}/download"
                    
                    print(f"📡 请求下载地址: {download_url_api}")
                    response = requests.get(download_url_api, headers=headers, timeout=10)
                    
                    print(f"📡 响应状态: {response.status_code}")
                    if response.status_code == 200:
                        result = response.json()
                        print(f"✓ 获取下载信息成功: {result}")
                        
                        # 可能的返回字段
                        download_url = result.get('downloadUrl') or result.get('url') or result.get('downloadInfo', {}).get('url')
                        
                        if download_url:
                            print(f"📥 正在从URL下载: {download_url[:50]}...")
                            file_response = requests.get(download_url, timeout=60, trust_env=False)
                            file_response.raise_for_status()
                            file_path = self._save_downloaded_file(file_response.content, file_name, save_dir)
                            return file_path
                    else:
                        print(f"⚠️ 响应内容: {response.text}")
                except Exception as e:
                    print(f"⚠️ 方式0失败: {e}")
            
            # 方式1: 使用媒体文件下载API
            try:
                # 根据官方文档，应该使用媒体文件下载接口
                download_url_api = f"{config.DINGTALK_API_BASE_URL}/v1.0/oauth2/userAccessToken"
                
                print(f"📡 方式1: 尝试获取媒体下载URL")
                
                # 直接POST请求下载
                download_api = f"{config.DINGTALK_API_BASE_URL}/v1.0/robot/messageFiles/download"
                
                response = requests.post(
                    download_api,
                    headers=headers,
                    json={'downloadCode': download_code},
                    timeout=10
                )
                
                print(f"📡 响应状态: {response.status_code}")
                if response.status_code == 200:
                    result = response.json()
                    print(f"✓ 获取下载信息成功: {result}")
                    download_url = result.get('downloadUrl') or result.get('url')
                    
                    if download_url:
                        # 下载文件
                        print(f"📥 正在从URL下载: {download_url[:50]}...")
                        file_response = requests.get(download_url, timeout=60, trust_env=False)
                        file_response.raise_for_status()
                        
                        # 保存文件并返回
                        file_path = self._save_downloaded_file(file_response.content, file_name, save_dir)
                        return file_path
                else:
                    print(f"⚠️ 响应内容: {response.text}")
                        
            except Exception as e:
                print(f"⚠️ 方式1失败: {e}")
            
            # 方式2: 尝试其他下载端点
            try:
                download_url_api = f"{config.DINGTALK_API_BASE_URL}/v1.0/im/interconnections/files/download"
                response = requests.get(download_url_api, headers=headers, params={'downloadCode': download_code}, timeout=10)
                
                if response.status_code == 200:
                    download_url = response.json().get('downloadUrl')
                    if download_url:
                        print(f"✓ 方式2成功获取下载地址")
                        file_response = requests.get(download_url, timeout=60, trust_env=False)
                        file_response.raise_for_status()
                        file_path = self._save_downloaded_file(file_response.content, file_name, save_dir)
                        return file_path
            except Exception as e:
                print(f"⚠️ 方式2失败: {e}")
            
            # 方式3: downloadCode可能就是可访问的URL
            if download_code.startswith('http'):
                print(f"✓ downloadCode本身是URL，直接下载")
                file_response = requests.get(download_code, headers=headers, timeout=60, trust_env=False)
                file_response.raise_for_status()
                file_path = self._save_downloaded_file(file_response.content, file_name, save_dir)
                return file_path
            
            # 如果所有方式都失败
            raise Exception(f"所有下载方式都失败，无法下载文件: {file_name}")
            
        except Exception as e:
            print(f"❌ 下载文件失败: {e}")
            raise
    
    def _save_downloaded_file(self, file_content: bytes, file_name: str, save_dir: str) -> str:
        """
        保存下载的文件到本地
        
        Args:
            file_content: 文件内容（字节）
            file_name: 文件名
            save_dir: 保存目录
            
        Returns:
            本地文件路径
        """
        os.makedirs(save_dir, exist_ok=True)
        # 添加时间戳避免文件名冲突
        timestamp = int(time.time())
        base_name, ext = os.path.splitext(file_name)
        unique_file_name = f"{base_name}_{timestamp}{ext}"
        file_path = os.path.join(save_dir, unique_file_name)
        
        with open(file_path, 'wb') as f:
            f.write(file_content)
        
        print(f"✅ 文件已保存到: {file_path}")
        return file_path
    
    def upload_file(
        self,
        file_path: str,
        channel: str = 'openapi',
        allow_fallback: bool = True,
        robot_code: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        上传文件到钉钉
        
        Args:
            file_path: 本地文件路径
            channel: 上传通道
                - openapi: 机器人会话/Stream模式使用（返回mediaId）
                - oapi: 企业内部应用上传通道（返回media_id，用于兼容旧接口）
            robot_code: Stream机器人robotCode。若不提供，则使用配置中的默认值
        
        Returns:
            (media_id, file_name) 元组
        """
        try:
            access_token = self.get_corp_access_token()
            file_name = os.path.basename(file_path)
            print(f"📤 正在上传文件[oapi]: {file_name}")
            upload_url = f"{config.DINGTALK_OAPI_BASE_URL}/media/upload"
            with open(file_path, 'rb') as f:
                files = {
                    'media': (file_name, f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                }
                params = {'access_token': access_token, 'type': 'file'}
                print(f"📡 使用企业内部应用上传: {upload_url}")
                response = requests.post(upload_url, files=files, params=params, timeout=60)
            print(f"📡 响应状态: {response.status_code}")
            if response.status_code == 200:
                result = response.json()
                print(f"✓ 上传响应: {result}")
                media_id = result.get('media_id')
                if media_id:
                    print(f"✅ 文件上传成功，media_id: {media_id}")
                    return media_id, file_name
                raise Exception(f"未返回media_id: {result}")
            raise Exception(f"{response.status_code}: {response.text[:200]}")
        except Exception as e:
            print(f"❌ 上传文件失败: {e}")
            raise

    def send_file_message(self, user_id: str, media_id: str, file_name: str, webhook: str = None) -> bool:
        """
        发送文件消息给指定用户（Stream模式使用webhook）
        
        Args:
            user_id: 用户ID（用于日志）
            media_id: 文件mediaId（从upload返回的）
            file_name: 文件名
            webhook: session_webhook地址（Stream模式）
            
        Returns:
            是否发送成功
        """
        try:
            # 方式1: 使用webhook（Stream模式，推荐）
            if webhook:
                print(f"📨 使用webhook发送文件...")
                
                file_message = {
                    "msgtype": "file",
                    "file": {
                        "mediaId": media_id,
                        "fileName": file_name,
                        "fileType": "xlsx"
                    }
                }
                
                response = requests.post(
                    webhook,
                    json=file_message,
                    headers={'Content-Type': 'application/json'},
                    timeout=10
                )
                
                print(f"📨 响应状态: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('errcode') == 0:
                        print(f"✅ 文件消息已发送给用户: {user_id}")
                        return True
                    else:
                        print(f"⚠️ 发送失败: {result}")
                        return False
            
            # 方式2: 通过机器人主动推送（不依赖传统通知）
            print(f"⚠️ 未提供webhook，尝试由机器人主动发送文件")
            return self.send_robot_oto_message(
                user_ids=user_id,
                msg_key="sampleFile",
                msg_param={
                    "mediaId": media_id,
                    "fileName": file_name
                }
            )
            
        except Exception as e:
            print(f"❌ 发送文件消息失败: {e}")
            return False
    
    def send_robot_oto_message(self, user_ids: Union[str, Sequence[str]], msg_key: str, msg_param: dict) -> bool:
        """
        使用机器人OpenAPI主动发送单聊消息
        
        Args:
            user_ids: 用户ID或ID列表
            msg_key: 钉钉内置消息模板（sampleText/sampleFile等）
            msg_param: 模板参数
        """
        try:
            if isinstance(user_ids, str):
                target_user_ids = [user_ids] if user_ids else []
            else:
                target_user_ids = [uid for uid in user_ids if uid]
            
            if not target_user_ids:
                raise ValueError("至少需要一个接收用户ID")
            
            if not self.client_id:
                raise ValueError("缺少robotCode（client_id）配置")
            
            access_token = self.get_access_token()
            url = f"{config.DINGTALK_API_BASE_URL}/v1.0/robot/oToMessages/batchSend"
            headers = {
                'x-acs-dingtalk-access-token': access_token
            }
            payload = {
                "robotCode": self.client_id,
                "userIds": target_user_ids,
                "msgKey": msg_key,
                "msgParam": json.dumps(msg_param, ensure_ascii=False)
            }
            
            print(f"\n{'='*70}")
            print(f"📨 机器人主动推送")
            print(f"{'='*70}")
            print(f"接收用户: {target_user_ids}")
            print(f"msgKey: {msg_key}")
            print(f"msgParam: {msg_param}")
            print(f"{'='*70}\n")
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            print(f"📨 响应状态: {response.status_code}")
            print(f"📨 响应内容: {response.text}\n")
            
            if response.status_code == 200:
                result = response.json() if response.text else {}
                error_code = result.get('code')
                if error_code in (None, '', 0, '0'):
                    print(f"✅ 机器人消息发送成功: {target_user_ids}")
                    return True
                print(f"❌ 机器人消息发送失败: {result}")
                return False
            
            print(f"❌ 机器人消息发送失败（HTTP {response.status_code}）")
            return False
        except Exception as e:
            print(f"❌ 机器人消息发送异常: {e}")
            return False
    
    def send_interactive_card(self, webhook: str, card_data: dict) -> bool:
        """
        发送交互式卡片（支持按钮回调）
        
        Args:
            webhook: session_webhook地址
            card_data: 卡片数据结构
            
        Returns:
            是否发送成功
        """
        try:
            print(f"📨 发送交互式卡片")
            print(f"📨 卡片数据: {card_data}")
            
            response = requests.post(
                webhook,
                json=card_data,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            print(f"📨 响应状态: {response.status_code}")
            print(f"📨 响应内容: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get('errcode') == 0:
                    print(f"✅ 交互式卡片已发送")
                    return True
                else:
                    print(f"⚠️ 发送失败: {result}")
                    return False
            
            return False
            
        except Exception as e:
            print(f"❌ 发送交互式卡片失败: {e}")
            return False
    
    def send_text_message(self, user_ids: Union[str, Sequence[str]], text: str) -> bool:
        """
        发送文本消息给指定用户
        
        Args:
            user_ids: 用户ID或ID列表
            text: 文本内容
            
        Returns:
            是否发送成功
        """
        try:
            return self.send_robot_oto_message(
                user_ids=user_ids,
                msg_key="sampleText",
                msg_param={"content": text}
            )
            
        except Exception as e:
            print(f"❌ 发送文本消息失败: {e}")
            return False
    


def cleanup_old_files(directory: str, days: int = 7, exclude: Optional[Sequence[str]] = None):
    """
    清理指定目录下超过指定天数的文件
    
    Args:
        directory: 目录路径
        days: 保留天数
    """
    if not os.path.exists(directory):
        return
    
    excluded_names = set(exclude or [])
    
    try:
        current_time = time.time()
        threshold = days * 24 * 60 * 60  # 转换为秒
        
        for entry_name in os.listdir(directory):
            if entry_name in excluded_names:
                continue
            entry_path = os.path.join(directory, entry_name)
            entry_age = current_time - os.path.getmtime(entry_path)
            if entry_age <= threshold:
                continue
            if os.path.isfile(entry_path):
                os.remove(entry_path)
                print(f"🗑️  已删除旧文件: {entry_path}")
            elif os.path.isdir(entry_path):
                shutil.rmtree(entry_path, ignore_errors=True)
                print(f"🗑️  已删除旧目录: {entry_path}")
    except Exception as e:
        print(f"⚠️  清理文件时出错: {e}")

