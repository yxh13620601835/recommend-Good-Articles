import os
from dotenv import load_dotenv

# 加载.env文件中的环境变量
load_dotenv()

class Config:
    # 飞书应用配置
    FEISHU_APP_ID = os.getenv('FEISHU_APP_ID')
    FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET')
    FEISHU_API_BASE_URL = 'https://open.feishu.cn/open-apis'
    FEISHU_AUTH_URL = f'{FEISHU_API_BASE_URL}/auth/v3/tenant_access_token/internal'
    FEISHU_BITABLE_URL = f'{FEISHU_API_BASE_URL}/bitable/v1'
    
    # API权限范围
    FEISHU_SCOPES = ['bitable:app:view', 'bitable:table:view', 'bitable:record:view']
    
    # 多维表格配置
    FEISHU_BASE_ID = os.getenv('FEISHU_BASE_ID')
    FEISHU_TABLE_ID = os.getenv('FEISHU_TABLE_ID')
    
    # API请求配置
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))  # API请求超时时间（秒）
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))  # API请求最大重试次数
    
    # Flask配置
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', os.urandom(24).hex())
    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'  # 默认关闭调试模式
    
    # 日志配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'WARNING')
    LOG_FORMAT = '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    LOG_MAX_BYTES = 1024 * 1024  # 1MB
    LOG_BACKUP_COUNT = 10