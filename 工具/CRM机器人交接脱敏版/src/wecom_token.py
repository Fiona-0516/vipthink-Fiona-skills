# -*- coding: utf-8 -*-
"""
企业微信 Access Token 管理模块
自动获取和刷新 Access Token
"""

import json
import time
import httpx
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class WeComTokenManager:
    """企业微信 Access Token 管理器"""
    
    TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    TOKEN_FILE = "wecom_token.json"
    
    def __init__(self, corp_id: str, corp_secret: str, token_file: str = None):
        """
        初始化 Token 管理器
        
        Args:
            corp_id: 企业ID
            corp_secret: 应用Secret
            token_file: Token缓存文件路径
        """
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.token_file = Path(token_file) if token_file else Path(__file__).parent / self.TOKEN_FILE
    
    def _load_token(self) -> Optional[dict]:
        """从文件加载Token"""
        try:
            if self.token_file.exists():
                with open(self.token_file, 'r') as f:
                    data = json.load(f)
                return data
        except Exception as e:
            logger.warning(f"Failed to load token from {self.token_file}: {e}")
        return None
    
    def _save_token(self, token_data: dict):
        """保存Token到文件"""
        try:
            with open(self.token_file, 'w') as f:
                json.dump(token_data, f, indent=2)
            logger.info(f"Token saved to {self.token_file}")
        except Exception as e:
            logger.error(f"Failed to save token: {e}")
    
    def get_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        获取 Access Token
        
        Args:
            force_refresh: 是否强制刷新
        
        Returns:
            Access Token 或 None
        """
        # 检查缓存的token是否有效
        if not force_refresh:
            cached = self._load_token()
            if cached:
                expires_at = cached.get('expires_at', 0)
                access_token = cached.get('access_token')
                if access_token and time.time() < expires_at - 300:  # 提前5分钟刷新
                    logger.debug("Using cached access token")
                    return access_token
        
        # 获取新token
        return self._fetch_access_token()
    
    def _fetch_access_token(self) -> Optional[str]:
        """从企业微信API获取Access Token"""
        params = {
            'corpid': self.corp_id,
            'corpsecret': self.corp_secret
        }
        
        try:
            logger.info(f"Fetching access token from WeCom API...")
            with httpx.Client(timeout=30) as client:
                response = client.get(self.TOKEN_URL, params=params)
                result = response.json()
            
            if result.get('errcode') == 0:
                access_token = result['access_token']
                expires_in = result.get('expires_in', 7200)
                
                token_data = {
                    'access_token': access_token,
                    'expires_at': time.time() + expires_in,
                    'fetched_at': time.time()
                }
                self._save_token(token_data)
                
                logger.info(f"Access token fetched successfully, expires in {expires_in}s")
                return access_token
            else:
                logger.error(f"Failed to fetch access token: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Exception while fetching access token: {e}")
            return None
    
    def refresh_token(self) -> Optional[str]:
        """强制刷新Token"""
        return self._fetch_access_token()


# 全局实例
_token_manager: Optional[WeComTokenManager] = None


def init_token_manager(corp_id: str, corp_secret: str) -> WeComTokenManager:
    """初始化全局Token管理器"""
    global _token_manager
    _token_manager = WeComTokenManager(corp_id, corp_secret)
    return _token_manager


def get_token_manager() -> Optional[WeComTokenManager]:
    """获取全局Token管理器"""
    return _token_manager


def get_access_token(force_refresh: bool = False) -> Optional[str]:
    """获取Access Token的便捷函数"""
    if _token_manager:
        return _token_manager.get_access_token(force_refresh)
    return None


if __name__ == '__main__':
    # 测试Token获取
    logging.basicConfig(level=logging.INFO)
    
    corp_id = "<WECOM_CORP_ID>"
    corp_secret = "<WECOM_SECRET>"
    
    manager = WeComTokenManager(corp_id, corp_secret)
    token = manager.get_access_token()
    
    if token:
        print(f"Access Token: {token[:20]}...")
    else:
        print("Failed to get access token")
