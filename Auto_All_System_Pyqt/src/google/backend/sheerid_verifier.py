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
