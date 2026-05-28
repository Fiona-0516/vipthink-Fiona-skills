# -*- coding: utf-8 -*-
"""
企业微信消息加解密模块
参考：https://developer.work.weixin.qq.com/document/path/90930
"""

import base64
import hashlib
import struct
import random
import string
import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad, pad


class WeComCrypto:
    """企业微信消息加解密类"""
    
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        """
        初始化加解密类
        
        Args:
            token: Callback Token
            encoding_aes_key: 43位Base64编码的AES密钥
            corp_id: 企业ID（用于验证消息来源）
        """
        self.token = token
        self.encoding_aes_key = encoding_aes_key
        self.corp_id = corp_id
        
        # 解码AES Key（32字节）
        self.aes_key = base64.b64decode(encoding_aes_key + '=')
        if len(self.aes_key) != 32:
            raise ValueError(f"Invalid AES key length: {len(self.aes_key)}, expected 32")
    
    def verify_signature(self, timestamp: str, nonce: str, msg_encrypt: str, signature: str) -> bool:
        """
        验证消息签名
        
        Args:
            timestamp: 时间戳
            nonce: 随机字符串
            msg_encrypt: 加密消息
            signature: 待验证签名
        
        Returns:
            签名是否正确
        """
        # 签名格式：SHA1(sort([token, timestamp, nonce, msg_encrypt]))
        sort_list = sorted([self.token, timestamp, nonce, msg_encrypt])
        sign_str = ''.join(sort_list)
        
        # 使用hashlib进行SHA1计算
        computed_signature = hashlib.sha1(sign_str.encode('utf-8')).hexdigest()
        
        return computed_signature == signature
    
    def encrypt_msg(self, reply_msg: str) -> tuple:
        """
        加密回复消息
        
        Args:
            reply_msg: 回复的明文消息
        
        Returns:
            (加密消息, 签名)
        """
        # 生成16字节随机字符串
        random_str = os.urandom(16)
        
        # 构建明文：random(16) + msg_len(4) + msg + corp_id
        msg_bytes = reply_msg.encode('utf-8')
        msg_len = struct.pack('>I', len(msg_bytes))  # 网络序（Big Endian）4字节长度
        
        # 明文 = random(16) + msg_len(4) + msg + corp_id
        plaintext = random_str + msg_len + msg_bytes + self.corp_id.encode('utf-8')
        
        # AES CBC加密，IV = AES Key的前16字节
        aes = AES.new(self.aes_key, AES.MODE_CBC, iv=self.aes_key[:16])
        # PKCS7填充
        padded_plaintext = pad(plaintext, AES.block_size, style='pkcs7')
        encrypted = aes.encrypt(padded_plaintext)
        
        # Base64编码
        msg_encrypt = base64.b64encode(encrypted).decode('ascii')
        
        # 生成签名
        timestamp = str(int(os.time.time())) if hasattr(os, 'time') else str(random.randint(1000000000, 2000000000))
        nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        sort_list = sorted([self.token, timestamp, nonce, msg_encrypt])
        sign_str = ''.join(sort_list)
        signature = hashlib.sha1(sign_str.encode('utf-8')).hexdigest()
        
        return msg_encrypt, signature, timestamp, nonce
    
    def decrypt_msg(self, msg_encrypt: str) -> str:
        """
        解密接收到的消息
        
        Args:
            msg_encrypt: 加密的消息
        
        Returns:
            解密后的明文XML消息
        """
        # Base64解码
        encrypted = base64.b64decode(msg_encrypt)
        
        # AES CBC解密
        aes = AES.new(self.aes_key, AES.MODE_CBC, iv=self.aes_key[:16])
        decrypted = aes.decrypt(encrypted)
        
        # 去除PKCS7填充
        try:
            decrypted = unpad(decrypted, AES.block_size, style='pkcs7')
        except ValueError as e:
            # 尝试不使用填充
            decrypted = decrypted.rstrip(b'\x00').rstrip(b'\x10')
        
        decrypted_bytes = bytes(decrypted)
        
        # 解析：random(16) + msg_len(4) + msg + from_corp_id
        # 去掉随机字符串（16字节）和长度字段（4字节）
        msg_len = struct.unpack('>I', decrypted_bytes[16:20])[0]
        msg_start = 20
        msg_end = msg_start + msg_len
        
        msg_content = decrypted_bytes[msg_start:msg_end].decode('utf-8')
        
        # 验证corp_id（取消息后32字节）
        from_corp_id = decrypted_bytes[msg_end:msg_end+len(self.corp_id)].decode('utf-8')
        if from_corp_id != self.corp_id:
            raise ValueError(f"Invalid corp_id: {from_corp_id}, expected {self.corp_id}")
        
        return msg_content


def parse_xml_text(xml_str: str) -> str:
    """从XML中提取CDATA内的文本"""
    if '<![CDATA[' in xml_str:
        import re
        match = re.search(r'<!\[CDATA\[(.*?)\]\]>', xml_str, re.DOTALL)
        if match:
            return match.group(1)
    return xml_str


def extract_xml_field(xml_str: str, field: str) -> str:
    """从XML中提取指定字段的值"""
    import re
    # 支持CDATA和非CDATA格式
    pattern = f'<{field}><!\\[CDATA\\[(.*?)\\]\\]></{field}>|<{field}>(.*?)</{field}>'
    match = re.search(pattern, xml_str, re.DOTALL)
    if match:
        return match.group(1) or match.group(2) or ''
    return ''


# ============== 独立加解密函数 ==============

def verify_signature(token: str, timestamp: str, nonce: str, msg_encrypt: str) -> str:
    """
    计算消息签名（用于验证）
    
    Returns:
        签名字符串
    """
    sort_list = sorted([token, timestamp, nonce, msg_encrypt])
    sign_str = ''.join(sort_list)
    return hashlib.sha1(sign_str.encode('utf-8')).hexdigest()


def decrypt_message(encoding_aes_key: str, msg_encrypt: str, corp_id: str) -> str:
    """
    解密企业微信消息
    
    Args:
        encoding_aes_key: 43位Base64编码的AES密钥
        msg_encrypt: 加密的消息
        corp_id: 企业ID
    
    Returns:
        解密后的XML消息
    """
    crypto = WeComCrypto('', encoding_aes_key, corp_id)
    return crypto.decrypt_msg(msg_encrypt)


def encrypt_message(token: str, encoding_aes_key: str, reply_msg: str, corp_id: str = '') -> dict:
    """
    加密回复消息
    
    Args:
        token: Callback Token
        encoding_aes_key: 43位Base64编码的AES密钥
        reply_msg: 回复的明文消息
        corp_id: 企业ID（用于消息来源验证）
    
    Returns:
        dict: 包含 encrypt, msg_signature, timestamp, nonce
    """
    import time
    # 生成随机字符串
    random_str = os.urandom(16)
    
    # 构建明文
    msg_bytes = reply_msg.encode('utf-8')
    msg_len = struct.pack('>I', len(msg_bytes))
    
    # 明文 = random(16) + msg_len(4) + msg + corp_id
    plaintext = random_str + msg_len + msg_bytes + corp_id.encode('utf-8')
    
    # AES CBC加密
    aes_key = base64.b64decode(encoding_aes_key + '=')
    aes = AES.new(aes_key, AES.MODE_CBC, iv=aes_key[:16])
    padded_plaintext = pad(plaintext, AES.block_size, style='pkcs7')
    encrypted = aes.encrypt(padded_plaintext)
    msg_encrypt = base64.b64encode(encrypted).decode('ascii')
    
    # 生成签名
    timestamp = str(int(time.time()))
    nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    signature = verify_signature(token, timestamp, nonce, msg_encrypt)
    
    return {
        'encrypt': msg_encrypt,
        'msg_signature': signature,
        'timestamp': timestamp,
        'nonce': nonce
    }


if __name__ == '__main__':
    # 测试加解密
    TOKEN = '<WECOM_CALLBACK_TOKEN>'
    AES_KEY = '<WECOM_ENCODING_AES_KEY>'
    CORP_ID = '<WECOM_CORP_ID>'
    
    crypto = WeComCrypto(TOKEN, AES_KEY, CORP_ID)
    
    # 测试签名验证
    timestamp = '1234567890'
    nonce = 'test_nonce'
    msg_encrypt = 'test_msg'
    
    sig = verify_signature(TOKEN, timestamp, nonce, msg_encrypt)
    print(f"Generated signature: {sig}")
    print(f"Verify result: {crypto.verify_signature(timestamp, nonce, msg_encrypt, sig)}")
    
    # 完整加解密测试
    print("\n=== Full encrypt/decrypt test ===")
    test_msg = '<xml><ToUserName><![CDATA[test]]></ToUserName></xml>'
    result = encrypt_message(TOKEN, AES_KEY, test_msg, CORP_ID)
    print(f"Encrypted keys: {result.keys()}")
    print(f"Signature: {result['msg_signature']}")
    
    decrypted = crypto.decrypt_msg(result['encrypt'])
    print(f"Decrypted: {decrypted}")
    print(f"Match: {decrypted == test_msg}")
