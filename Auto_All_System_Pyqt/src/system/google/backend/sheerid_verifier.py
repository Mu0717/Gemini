"""
@file sheerid_verifier.py
@brief SheerID Verification Module (V3 - Lacedore API)
@details Verification via http://lacedore.org:6789
@api_doc http://lacedore.org:6789/docs
"""
import requests
import json
import time
import logging
from typing import List, Dict, Optional, Callable

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API Configuration
BASE_URL = "http://lacedore.org:6789"
DEFAULT_API_KEY = ""

class SheerIDVerifier:
    """
    @class SheerIDVerifier
    @brief SheerID Batch Verifier
    @details Encapsulates lacedore.org verification API
    
    API Endpoints:
    - GET  /quota          : Check credits
    - GET  /upstream/status: Check upstream status
    - POST /verify/batch   : Batch verify
    - POST /cancel         : Cancel verification
    """
    
    def __init__(self, api_key: str = DEFAULT_API_KEY):
        """
        @brief Initialize verifier
        @param api_key API Key
        """
        self.session = requests.Session()
        
        # Keep-Alive & Retry Strategy
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.api_key = api_key
        self.quota_info = {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }

    def get_system_status(self) -> Dict:
        """
        @brief Get system status and quota
        @return System status info
        """
        result = {
            "status": "unknown",
            "availableSlots": 100,  # Default assumptions
            "activeJobs": 0,
            "maxConcurrent": 10
        }
        
        # 1. Check Upstream Status
        try:
            resp = self.session.get(f"{BASE_URL}/upstream/status", headers=self.headers, timeout=30)
            if resp.status_code == 200:
                upstream_data = resp.json()
                if upstream_data.get('available'):
                    result['status'] = 'ok'
                    result['upstream_latency'] = upstream_data.get('latency_ms')
                else:
                    result['status'] = 'error'
                    result['message'] = upstream_data.get('error', 'Upstream unavailable')
            else:
                result['status'] = 'error'
                result['message'] = f"Upstream check failed: {resp.status_code}"
        except Exception as e:
            result['status'] = 'error'
            result['message'] = f"Connection error: {str(e)}"
            return result

        # 2. Check Quota (if upstream is ok or even if not)
        try:
            resp = self.session.get(f"{BASE_URL}/quota", headers=self.headers, timeout=30)
            if resp.status_code == 200:
                quota_data = resp.json()
                credits = quota_data.get('credits', 0)
                result['current_quota'] = credits
                
                # Update local cache and DB
                self.quota_info = {"current_quota": credits, "updated_at": int(time.time())}
                self._save_quota_to_db(self.quota_info)
        except Exception as e:
            logger.warning(f"Failed to fetch quota: {e}")

        return result

    def verify_single(self, verification_id: str, callback: Callable = None) -> Dict:
        """
        @brief Single verification with dynamic status polling
        @param verification_id Verification ID
        @param callback Status callback function(vid, message)
        @return Verification result
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
                        
                    # Poll status dynamically
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
                            
                            # Merge API response into our result dictionary
                            for k, v in status_data.items():
                                if k not in ["task_id", "status", "api_key"]:
                                    result[k] = v
                                    
                            result["currentStep"] = current_step
                            result["message"] = msg
                            
                            if callback:
                                callback(verification_id, f"Step: {current_step} | Msg: {msg}")
                                
                            if status in ["completed", "error"]:
                                break # Task finished
                        else:
                            logger.warning(f"Status check failed for {task_id}: HTTP {status_resp.status_code}")
                            
                        # Exponential backoff up to max_poll_interval
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
        @brief Batch verification with chunking
        @param verification_ids List of verification IDs
        @param callback Status callback function(vid, message)
        @return Verification results {verification_id: result}
        """
        if not verification_ids:
            return {}

        self.headers["X-API-Key"] = self.api_key
        
        # Chunking configuration to avoid overwhelming the server
        CHUNK_SIZE = 50
        results = {}
        
        chunks = [verification_ids[i:i + CHUNK_SIZE] for i in range(0, len(verification_ids), CHUNK_SIZE)]
        logger.info(f"📤 Submitting async batch verification: {len(verification_ids)} IDs in {len(chunks)} chunks")
        
        if callback:
            callback(None, f"Starting async batch verification for {len(verification_ids)} items ({len(chunks)} chunks)...")

        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)} ({len(chunk)} items)")
            
            active_tasks = {}
            
            # 1. Submit tasks for the current chunk
            for vid in chunk:
                # Initialize result
                results[vid] = {"currentStep": "pending", "message": "Creating task..."}
                if callback:
                    callback(vid, "Step: pending | Msg: Creating task...")
                    
                try:
                    url = f"{BASE_URL}/verify"
                    payload = {"verification_id": vid}
                    resp = self.session.post(url, headers=self.headers, json=payload, timeout=15)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        task_id = data.get("task_id")
                        if task_id:
                            active_tasks[vid] = task_id
                            results[vid]["message"] = "Task created, waiting for processing..."
                            if callback:
                                callback(vid, "Step: pending | Msg: Task created, waiting for processing...")
                        else:
                            results[vid]["currentStep"] = "error"
                            results[vid]["message"] = "API response missing task_id"
                            if callback:
                                callback(vid, "Step: error | Msg: API response missing task_id")
                    else:
                        msg = f"HTTP {resp.status_code}: {resp.text}"
                        results[vid]["currentStep"] = "error"
                        results[vid]["message"] = msg
                        if callback:
                            callback(vid, f"Step: error | Msg: {msg}")
                            
                except Exception as e:
                    msg = f"Connection error: {str(e)}"
                    results[vid]["currentStep"] = "error"
                    results[vid]["message"] = msg
                    if callback:
                        callback(vid, f"Step: error | Msg: {msg}")
                        
                # Small delay to avoid overwhelming the server
                time.sleep(0.1)
                
            # 2. Poll statuses until all tasks in this chunk are completed
            poll_interval = 2.0
            max_poll_interval = 5.0
            
            while active_tasks:
                time.sleep(poll_interval)
                still_active = {}
                
                for vid, task_id in active_tasks.items():
                    try:
                        status_url = f"{BASE_URL}/verify/status/{task_id}"
                        resp = self.session.get(status_url, headers=self.headers, timeout=10)
                        
                        if resp.status_code == 200:
                            data = resp.json()
                            status = data.get("status", "unknown")
                            current_step = data.get("currentStep", status)
                            msg = data.get("message", "")
                            
                            # Merge API response into our result dictionary
                            for k, v in data.items():
                                if k not in ["task_id", "status", "api_key"]:
                                    results[vid][k] = v
                                    
                            results[vid]["currentStep"] = current_step
                            results[vid]["message"] = msg
                            
                            if callback:
                                callback(vid, f"Step: {current_step} | Msg: {msg}")
                                
                            if status in ["completed", "error"]:
                                pass # Task finished
                            else:
                                still_active[vid] = task_id # Still processing
                        else:
                            logger.warning(f"Status check failed for {task_id}: HTTP {resp.status_code}")
                            still_active[vid] = task_id
                            
                    except Exception as e:
                        logger.warning(f"Error checking status for {task_id}: {e}")
                        still_active[vid] = task_id
                        
                active_tasks = still_active
                poll_interval = min(poll_interval + 0.5, max_poll_interval)

        # Final quota update
        try:
            self.get_system_status() 
        except:
            pass

        return results

    def redeem_code(self, code: str) -> Dict:
        """
        @brief Redeem credit code
        @param code Card code
        """
        url = f"{BASE_URL}/redeem"
        payload = {"code": code}
        
        try:
            resp = self.session.post(url, headers=self.headers, json=payload, timeout=30)
            result = resp.json()
            
            # If successful, update local quota
            if result.get('credits_added') is not None:
                # We can trust the response's credits_total or fetch fresh
                if 'credits_total' in result:
                    self.quota_info = {"current_quota": result['credits_total'], "updated_at": int(time.time())}
                    self._save_quota_to_db(self.quota_info)
            
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def cancel_verification(self, verification_id: str) -> Dict:
        """
        @brief Cancel verification
        """
        url = f"{BASE_URL}/cancel"
        payload = {"verification_id": verification_id}
        
        try:
            resp = self.session.post(url, headers=self.headers, json=payload, timeout=30)
            return resp.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _save_quota_to_db(self, info: Dict):
        """
        @brief Save quota info to database
        """
        try:
            from core.database import DBManager
            import json as json_module
            DBManager.set_setting('sheerid_quota', json_module.dumps(info))
            DBManager.set_setting('sheerid_quota_time', str(int(time.time())))
        except Exception as e:
            logger.warning(f"Failed to save quota to DB: {e}")

if __name__ == "__main__":
    pass
