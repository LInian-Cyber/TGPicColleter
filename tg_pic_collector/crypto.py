"""
crypto.py - Session encryption using Windows DPAPI
"""
from __future__ import annotations

import sys
from pathlib import Path


def encrypt_session(session_path: Path, use_encryption: bool = True) -> bool:
    """
    使用 Windows DPAPI 加密 session 文件
    
    Args:
        session_path: session 文件路径（不含 .session 后缀）
        use_encryption: 是否启用加密
        
    Returns:
        是否成功加密
    """
    if not use_encryption or sys.platform != "win32":
        return False
        
    try:
        import win32crypt
        
        session_file = Path(f"{session_path}.session")
        if not session_file.exists():
            return False
            
        # 读取原始数据
        data = session_file.read_bytes()
        
        # 使用 DPAPI 加密
        encrypted = win32crypt.CryptProtectData(
            data,
            "TelegramSession",
            None,
            None,
            None,
            0
        )
        
        # 写回加密后的数据
        encrypted_file = Path(f"{session_path}.session.encrypted")
        encrypted_file.write_bytes(encrypted)
        
        # 删除原文件
        session_file.unlink()
        encrypted_file.rename(session_file)
        
        return True
        
    except (ImportError, OSError):
        return False


def decrypt_session(session_path: Path) -> bool:
    """
    解密使用 DPAPI 加密的 session 文件
    
    Args:
        session_path: session 文件路径（不含 .session 后缀）
        
    Returns:
        是否成功解密
    """
    if sys.platform != "win32":
        return False
        
    try:
        import win32crypt
        
        session_file = Path(f"{session_path}.session")
        if not session_file.exists():
            return False
            
        # 读取加密数据
        encrypted = session_file.read_bytes()
        
        # 尝试解密
        try:
            decrypted = win32crypt.CryptUnprotectData(
                encrypted,
                None,
                None,
                None,
                0
            )[1]
            
            # 写回解密后的数据
            decrypted_file = Path(f"{session_path}.session.decrypted")
            decrypted_file.write_bytes(decrypted)
            
            # 替换原文件
            session_file.unlink()
            decrypted_file.rename(session_file)
            
            return True
            
        except Exception:
            # 数据可能未加密，直接返回
            return False
            
    except (ImportError, OSError):
        return False


def is_session_encrypted(session_path: Path) -> bool:
    """
    检测 session 文件是否已加密
    
    Args:
        session_path: session 文件路径（不含 .session 后缀）
        
    Returns:
        是否已加密
    """
    if sys.platform != "win32":
        return False
        
    try:
        import win32crypt
        
        session_file = Path(f"{session_path}.session")
        if not session_file.exists():
            return False
            
        # 读取文件头部
        data = session_file.read_bytes()[:100]
        
        # 尝试解密前几个字节来判断
        try:
            win32crypt.CryptUnprotectData(data, None, None, None, 0)
            return True
        except Exception:
            return False
            
    except (ImportError, OSError):
        return False
