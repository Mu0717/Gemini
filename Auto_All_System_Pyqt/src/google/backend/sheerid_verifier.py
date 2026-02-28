"""
@file sheerid_verifier.py
@brief SheerID学生验证器模块 (V3 - 基于 lacedore.org API)
@details 通过 lacedore.org API 进行 Google 学生资格验证
@api_doc http://lacedore.org:6789/docs
"""
import requests
import json
import logging
import time
from typing import List, Dict, Optional, Callable

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API 配置
BASE_URL = "http://lacedore.org:6789"
DEFAULT_API_KEY = ""


class SheerIDVerifier:
    """
    @class SheerIDVerifier
    @brief SheerID 批量验证器
    @details 封装 lacedore.org 批量验证 API
    
    API 端点:
    - POST /verify/batch   : 批量验证
    - GET  /quota          : 获取配额信息
    - POST /redeem         : 兑换卡密
    """
    
    def __init__(self, api_key: str = DEFAULT_API_KEY):
        """
        @brief 初始化验证器
        @param api_key API 密钥
        """
        self.session = requests.Session()
        self.api_key = api_key.strip()
        self.quota_info = {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "X-API-Key": self.api_key
        }

    def get_system_status(self) -> Dict:
        """
        @brief 获取系统状态 (适配旧接口返回格式)
        @return 系统状态信息
        """
        try:
            resp = self.session.get(f"{BASE_URL}/quota", headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                # 适配旧接口的返回字段，以便前端能正常显示
                return {
                    "status": "ok",
                    "availableSlots": 999,  # 假数据
                    "activeJobs": 0,        # 假数据
                    "maxConcurrent": 10,    # 假数据
                    "credits": data.get("credits", 0)  # 真实剩余积分
                }
            return {"status": "error", "code": resp.status_code, "message": resp.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def verify_single(self, verification_id: str, callback: Callable = None) -> Dict:
        """
        @brief 单个验证状态轮询
        @param verification_id 验证ID
        @param callback 状态回调函数 callback(vid, message)
        @return 验证结果
        """
        if not verification_id:
            return {"currentStep": "error", "message": "No verification ID provided"}

        self.headers["X-API-Key"] = self.api_key
        result = {"currentStep": "pending", "message": "Creating task...", "verificationId": verification_id}
        
        if callback:
            callback(verification_id, "Step: pending | Msg: Creating task...")
            
        try:
            url = f"{BASE_URL}/verify"
            payload = {"verification_id": verification_id}
            resp = self.session.post(url, headers=self.headers, json=payload, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                task_id = data.get("task_id")
                if task_id:
                    result["message"] = "Task created, waiting for processing..."
                    if callback:
                        callback(verification_id, "Step: pending | Msg: Task created, waiting for processing...")
                        
                    # 动态轮询状态
                    poll_interval = 2.0
                    max_poll_interval = 5.0
                    
                    while True:
                        time.sleep(poll_interval)
                        status_url = f"{BASE_URL}/verify/status/{task_id}"
                        status_resp = self.session.get(status_url, headers=self.headers, timeout=10)
                        
                        if status_resp.status_code == 200:
                            status_data = status_resp.json()
                            status = status_data.get("status", "unknown")
                            current_step = status_data.get("currentStep", status)
                            msg = status_data.get("message", "")
                            
                            # 合并返回结果
                            for k, v in status_data.items():
                                if k not in ["task_id", "status", "api_key"]:
                                    result[k] = v
                                    
                            result["currentStep"] = current_step
                            result["message"] = msg
                            
                            if callback:
                                callback(verification_id, f"Step: {current_step} | Msg: {msg}")
                                
                            if status in ["completed", "error"]:
                                break # 任务完成
                        else:
                            logger.warning(f"Status check failed for {task_id}: HTTP {status_resp.status_code}")
                            
                        # 指数退避
                        poll_interval = min(poll_interval + 0.5, max_poll_interval)
                else:
                    result["currentStep"] = "error"
                    result["message"] = "API response missing task_id"
                    if callback:
                        callback(verification_id, "Step: error | Msg: API response missing task_id")
            else:
                msg = f"HTTP {resp.status_code}: {resp.text}"
                result["currentStep"] = "error"
                result["message"] = msg
                if callback:
                    callback(verification_id, f"Step: error | Msg: {msg}")
                    
        except Exception as e:
            msg = f"Connection error: {str(e)}"
            result["currentStep"] = "error"
            result["message"] = msg
            if callback:
                callback(verification_id, f"Step: error | Msg: {msg}")

        # Final quota update
        try:
            self.get_system_status() 
        except:
            pass

        return result

    def verify_batch(self, verification_ids: List[str], callback: Callable = None) -> Dict:
        """
        @brief 批量验证
        @param verification_ids 验证ID列表
        @param callback 状态回调函数 callback(vid, message)
        @return 验证结果字典 {verification_id: result}
        """
        results = {}
        
        payload = {
            "verification_ids": verification_ids
        }

        try:
            logger.info(f"📤 提交批量验证: {len(verification_ids)} 个 ID")
            
            # 确保 Headers 中有 API Key
            self.headers["X-API-Key"] = self.api_key
            
            resp = self.session.post(
                f"{BASE_URL}/verify/batch", 
                headers=self.headers, 
                json=payload,
                timeout=120  # 批量请求可能耗时较长
            )
            print('resp',resp)
            if resp.status_code == 200:
                data = resp.json()
                api_results = data.get("results", [])
                
                # 记录本次消耗
                if "credits_deducted" in data:
                    logger.info(f"本次消耗积分: {data['credits_deducted']}")
                
                for res in api_results:
                    vid = res.get("verificationId")
                    if not vid: continue
                    
                    # 转换格式以兼容旧逻辑
                    # API返回: { "verificationId": "...", "success": true, "message": "...", ... }
                    # 旧逻辑期待: { "currentStep": "success"/"error", "message": "..." }
                    
                    status = "success" if res.get("success") else "error"
                    msg = res.get("message", "")
                    
                    results[vid] = {
                        "currentStep": status,
                        "message": msg,
                        "data": res  # 保留原始数据
                    }
                    
                    if callback:
                        callback(vid, f"Step: {status} | Msg: {msg}")
                
                # 检查是否有未返回结果的 ID
                for vid in verification_ids:
                    if vid not in results:
                        results[vid] = {"currentStep": "error", "message": "API未返回结果"}
            
            else:
                error_msg = f"HTTP {resp.status_code}: {resp.text}"
                try:
                    err_json = resp.json()
                    error_msg = err_json.get("detail", error_msg) or err_json.get("message", error_msg)
                except:
                    pass
                    
                logger.error(f"批量请求失败: {error_msg}")
                for vid in verification_ids:
                    results[vid] = {"currentStep": "error", "message": error_msg}

        except Exception as e:
            logger.error(f"批量验证异常: {e}")
            for vid in verification_ids:
                results[vid] = {"currentStep": "error", "message": str(e)}

        return results

    def redeem(self, code: str) -> Dict:
        """
        @brief 兑换卡密
        @param code 卡密
        @return 兑换结果
        """
        try:
            payload = {"code": code}
            self.headers["X-API-Key"] = self.api_key
            
            resp = self.session.post(
                f"{BASE_URL}/redeem", 
                headers=self.headers, 
                json=payload,
                timeout=30
            )
            
            if resp.status_code == 200:
                return resp.json()
            else:
                try:
                    err_json = resp.json()
                    detail = err_json.get("detail") or err_json.get("message") or f"兑换失败 ({resp.status_code})"
                    return {"success": False, "error": detail}
                except:
                    return {"success": False, "error": f"兑换失败 ({resp.status_code}): {resp.text}"}
                    
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_verification(self, verification_id: str) -> dict:
        """
        @brief 取消验证 (新API暂不支持，保留为空方法)
        """
        return {"status": "error", "message": "Not supported in V3 API"}

if __name__ == "__main__":
    pass
