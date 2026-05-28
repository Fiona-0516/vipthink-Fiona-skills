#!/usr/bin/env python3
"""
CRM 自动化模块 - 通过 agent-browser 技能操作
"""

import logging
import requests
import json
import os

logger = logging.getLogger("CRM自动化")

# CRM 配置
# 注意：直接访问 https://crm.vipthink.cn 即可，会自动跳转到登录页
# 不要使用 passport.vipthink.cn 直接访问
CRM_URL = "https://crm.vipthink.cn"
CRM_ACCOUNT = "18827663792"
CRM_PASSWORD = "rKB.978Y@5"

# API 端点（调用 agent-browser 技能的 sub-agent）
# 这里我们通过写入任务文件，让主 session 来创建 sub-agent
TASK_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/crm_task.json"
RESULT_FILE = "/app/data/所有对话/主对话/dingtalk_stream_bot/crm_result.json"


class CRMBrowser:
    """CRM 浏览器自动化客户端 - 使用 agent-browser 技能"""
    
    def __init__(self):
        self.logged_in = False
    
    async def set_class_permission(self, class_id: str, permission: str, enable: bool) -> dict:
        """设置班级权限
        
        这个方法会写入任务文件，由主 session 的 sub-agent 来执行
        """
        permission_text = "允许补课" if permission == "makeup" else "允许插班"
        action = "开启" if enable else "关闭"
        
        # 构建任务描述
        task = {
            "action": "set_permission",
            "class_id": class_id,
            "permission": permission,
            "enable": enable,
            "description": f"""
在CRM系统中{action}班级{class_id}的{permission_text}权限。

步骤：
1. 打开登录页面: {CRM_URL}
2. 输入账号: {CRM_ACCOUNT}
3. 输入密码: {CRM_PASSWORD}
4. 点击登录按钮
5. 等待登录成功后，点击顶部"更多"按钮
6. 在展开菜单中点击"教务"
7. 在左侧导航中点击"班级管理"
8. 在班级管理页面，找到"班级ID"搜索框（筛选区第3个输入框）
9. 输入班级ID: {class_id}
10. 按回车搜索
11. 在搜索结果中点击班级ID链接进入详情页
12. 在详情页左侧"补课设置"区域，找到"{permission_text}"开关
13. 点击开关{action}该权限
14. 验证操作结果

注意：每次操作后需要验证是否成功。
"""
        }
        
        # 这里我们直接返回一个模拟结果
        # 实际执行需要主 session 调用 sessions_spawn
        return {
            "success": False, 
            "message": "需要通过 agent-browser 技能执行",
            "task": task
        }
    
    async def close(self):
        """关闭"""
        pass


# 全局单例
_crm_browser = None

def get_crm_browser() -> CRMBrowser:
    """获取 CRM 浏览器实例"""
    global _crm_browser
    if _crm_browser is None:
        _crm_browser = CRMBrowser()
    return _crm_browser
