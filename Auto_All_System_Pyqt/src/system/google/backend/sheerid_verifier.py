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
        url = f"{BASE_URL}/verify/batch"
        
        # Chunking configuration to avoid large payload errors
        CHUNK_SIZE = 50
        results = {}
        
        chunks = [verification_ids[i:i + CHUNK_SIZE] for i in range(0, len(verification_ids), CHUNK_SIZE)]
        logger.info(f"📤 Submitting batch verification: {len(verification_ids)} IDs in {len(chunks)} chunks")
        
        if callback:
            callback(None, f"Starting batch verification for {len(verification_ids)} items ({len(chunks)} chunks)...")

        for i, chunk in enumerate(chunks):
            try:
                logger.info(f"Processing chunk {i+1}/{len(chunks)} ({len(chunk)} items)")
                payload = {"verification_ids": chunk}
                
                # Request with extended timeout (300s) to handle server processing delays
                resp = self.session.post(url, headers=self.headers, json=payload, timeout=300)
                
                if resp.status_code != 200:
                    error_msg = f"HTTP {resp.status_code}: {resp.text}"
                    logger.error(f"Chunk {i+1} failed: {error_msg}")
                    for vid in chunk:
                        results[vid] = {"currentStep": "error", "message": error_msg}
                    continue
                
                data = resp.json()
                
                # Check forcredits deducted
                if 'credits_deducted' in data:
                    logger.info(f"Credits deducted (chunk {i+1}): {data['credits_deducted']}")

                api_results = data.get('results', [])
                
                for res in api_results:
                    vid = res.get('verificationId')
                    if vid:
                        results[vid] = res
                        if callback:
                            status = res.get('currentStep', 'unknown')
                            msg = res.get('message', '')
                            callback(vid, f"Step: {status} | Msg: {msg}")

                # Mark missing ones as errors
                for vid in chunk:
                    if vid not in results:
                        results[vid] = {"currentStep": "error", "message": "No response from API"}

            except Exception as e:
                logger.error(f"Chunk {i+1} verification failed: {e}")
                import traceback
                traceback.print_exc()
                for vid in chunk:
                    results[vid] = {"currentStep": "error", "message": f"Connection error: {str(e)}"}
            
            # Be nice to the server between chunks
            if i < len(chunks) - 1:
                time.sleep(1)

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
