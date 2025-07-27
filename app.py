from flask import Flask, render_template
from markupsafe import Markup
import requests
import json
import logging
import ast # 新增导入
from logging.handlers import RotatingFileHandler
import os
import time # 新增导入
from config import Config
from bleach import clean
from markdown import markdown
from jinja2 import Environment, FileSystemLoader # 导入 Environment 和 FileSystemLoader

app = Flask(__name__)

# 配置 Jinja2 环境
def nl2br(value):
    """将换行符转换为 <br> 标签"""
    return value.replace('\n', '<br>\n')

app.jinja_env.filters['nl2br'] = nl2br

def _convert_feishu_richtext_to_html(richtext_json):
    """将飞书富文本JSON转换为HTML"""
    if not richtext_json:
        return ""

    try:
        # 确保输入是字符串，并尝试解析为JSON
        if isinstance(richtext_json, str):
            data = json.loads(richtext_json)
        elif isinstance(richtext_json, (list, dict)):
            data = richtext_json
        else:
            return str(richtext_json) # 如果不是JSON也不是字符串，直接转字符串

        if not isinstance(data, list):
            # 如果不是列表，尝试从字典中获取'text'字段，或者直接返回其字符串表示
            if isinstance(data, dict) and 'text' in data:
                return clean(data['text'], tags=[], attributes={}, styles=[], strip=True)
            return clean(str(data), tags=[], attributes={}, styles=[], strip=True)

        html_parts = []
        for item in data:
            if not isinstance(item, dict):
                continue

            obj_type = item.get('type')
            content = item.get('text', '')
            url = item.get('url', '')
            children = item.get('children', [])

            # 清理内容，只保留文本，避免XSS
            cleaned_content = clean(content, tags=[], attributes={}, styles=[], strip=True)

            if obj_type == 'text':
                text = cleaned_content
                if item.get('bold'):
                    text = f"<strong>{text}</strong>"
                if item.get('italic'):
                    text = f"<em>{text}</em>"
                if item.get('underline'):
                    text = f"<u>{text}</u>"
                if item.get('strikethrough'):
                    text = f"<s>{text}</s>"
                if item.get('code'):
                    text = f"<code>{text}</code>"
                html_parts.append(text)
            elif obj_type == 'paragraph':
                # 递归处理段落内的子元素
                paragraph_content = _convert_feishu_richtext_to_html(children)
                html_parts.append(f"<p>{paragraph_content}</p>")
            elif obj_type == 'heading1':
                html_parts.append(f"<h1>{cleaned_content}</h1>")
            elif obj_type == 'heading2':
                html_parts.append(f"<h2>{cleaned_content}</h2>")
            elif obj_type == 'heading3':
                html_parts.append(f"<h3>{cleaned_content}</h3>")
            elif obj_type == 'bulleted_list':
                list_items = []
                for child in children:
                    if child.get('type') == 'list_item':
                        list_items.append(f"<li>{_convert_feishu_richtext_to_html(child.get('children', []))}</li>")
                html_parts.append(f"<ul>{''.join(list_items)}</ul>")
            elif obj_type == 'ordered_list':
                list_items = []
                for child in children:
                    if child.get('type') == 'list_item':
                        list_items.append(f"<li>{_convert_feishu_richtext_to_html(child.get('children', []))}</li>")
                html_parts.append(f"<ol>{''.join(list_items)}</ol>")
            elif obj_type == 'code_block':
                html_parts.append(f"<pre><code>{cleaned_content}</code></pre>")
            elif obj_type == 'quote':
                html_parts.append(f"<blockquote>{cleaned_content}</blockquote>")
            elif obj_type == 'hr':
                html_parts.append("<hr>")
            elif obj_type == 'image':
                # 飞书图片通常需要特殊处理，这里简化为显示一个占位符或跳过
                html_parts.append(f"<p>[图片: {cleaned_content}]</p>")
            elif obj_type == 'link':
                html_parts.append(f"<a href=\"{clean(url, tags=[], attributes={}, styles=[], strip=True)}\">{cleaned_content}</a>")
            # 可以根据需要添加更多类型

        return Markup(''.join(html_parts))
    except json.JSONDecodeError as e:
        app.logger.error(f"JSON解析错误: {e} - 原始数据: {richtext_json}")
        return clean(str(richtext_json), tags=[], attributes={}, styles=[], strip=True) # 解析失败返回清理后的原始字符串
    except Exception as e:
        app.logger.error(f"富文本转换错误: {e} - 原始数据: {richtext_json}")
        return clean(str(richtext_json), tags=[], attributes={}, styles=[], strip=True)

def _convert_to_string(value):
    """将值转换为字符串，处理列表和字典类型"""
    app.logger.debug(f"_convert_to_string: Input value type: {type(value)}, value: {value}")

    result = ""
    if isinstance(value, list):
        # 尝试将列表中的元素连接成字符串，如果元素是字典，则尝试提取其文本内容
        result = " ".join([str(item.get('text', item) if isinstance(item, dict) else item) for item in value])
    elif isinstance(value, dict):
        # 如果是字典，尝试提取其文本内容，或者转换为JSON字符串
        result = str(value.get('text', json.dumps(value)))
    elif isinstance(value, str):
        # 尝试解析为JSON，处理飞书富文本格式
        try:
            parsed_value = json.loads(value)
            app.logger.debug(f"_convert_to_string: JSON parsed_value type: {type(parsed_value)}, value: {parsed_value}")
            if isinstance(parsed_value, list) and all(isinstance(item, dict) and 'text' in item for item in parsed_value):
                # 假设是飞书富文本格式，只提取纯文本内容
                processed_parts = []
                for item in parsed_value:
                    if item.get('type') == 'text':
                        processed_parts.append(item['text'])
                result = " ".join(processed_parts)
            else:
                result = str(value) # 如果是JSON但不是预期的富文本格式，按普通字符串处理
        except json.JSONDecodeError:
            try:
                # 尝试使用 ast.literal_eval 处理单引号的字典或列表字符串
                parsed_value = ast.literal_eval(value)
                app.logger.debug(f"_convert_to_string: AST parsed_value type: {type(parsed_value)}, value: {parsed_value}")
                if isinstance(parsed_value, list) and all(isinstance(item, dict) and 'text' in item for item in parsed_value):
                    processed_parts = []
                    for item in parsed_value:
                        if item.get('type') == 'text':
                            processed_parts.append(item['text'])
                    result = " ".join(processed_parts)
                elif isinstance(parsed_value, dict):
                    result = str(parsed_value.get('text', str(parsed_value))) # 如果是字典，尝试提取其文本内容
                else:
                    result = str(value) # 如果是其他类型，按普通字符串处理
            except (ValueError, SyntaxError):
                result = str(value) # 不是JSON也不是有效的Python字面量，按普通字符串处理
    else:
        result = str(value)

    # 确保最终结果是字符串，并去除首尾空白
    final_result = str(result).strip()
    app.logger.debug(f"_convert_to_string: Output type: {type(final_result)}, value: {final_result}")
    return final_result
app.config.from_object(Config)

# 配置日志
def setup_logger():
    # 创建logs目录（如果不存在）
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # 设置日志格式
    formatter = logging.Formatter(Config.LOG_FORMAT)
    
    # 文件处理器 - 记录所有日志
    file_handler = RotatingFileHandler(
        'logs/app.log',
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, Config.LOG_LEVEL))
    
    # 错误日志文件处理器 - 只记录错误和严重错误
    error_file_handler = RotatingFileHandler(
        'logs/error.log',
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT
    )
    error_file_handler.setFormatter(formatter)
    error_file_handler.setLevel(logging.ERROR)
    
    # 开发环境下的控制台处理器
    if app.debug:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.DEBUG)
        app.logger.addHandler(console_handler)
    
    # 添加处理器到应用日志器
    app.logger.addHandler(file_handler)
    app.logger.addHandler(error_file_handler)
    
    # 设置日志级别
    app.logger.setLevel(getattr(logging, Config.LOG_LEVEL))

# 初始化日志配置
setup_logger()

def _make_api_request(method, url, headers=None, json_data=None, params=None, timeout=None, error_prefix="API请求"):
    """通用API请求函数，包含重试和错误处理"""
    for retry in range(Config.MAX_RETRIES):
        try:
            app.logger.debug(f"尝试 {method} 请求: {url}, 重试次数: {retry + 1}")
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json_data,
                params=params,
                timeout=timeout if timeout is not None else Config.REQUEST_TIMEOUT
            )
            response.raise_for_status()  # 检查HTTP状态码，如果不是2xx，则抛出HTTPError
            
            try:
                result = response.json()
            except json.JSONDecodeError as e:
                error_msg = f"{error_prefix}响应解析失败：{str(e)}"
                app.logger.error(error_msg)
                return None, error_msg

            if result.get('code', -1) == 0:
                return result, None
            else:
                error_msg = f"{error_prefix}失败：{result.get('msg', '未知错误')}"
                app.logger.error(error_msg)
                return None, error_msg

        except requests.exceptions.Timeout:
            if retry < Config.MAX_RETRIES - 1:
                app.logger.warning(f"{error_prefix}请求超时，正在重试 ({retry + 1}/{Config.MAX_RETRIES})")
                continue
            else:
                error_msg = f"{error_prefix}请求超时，已达最大重试次数"
                app.logger.error(error_msg)
                return None, error_msg
        except requests.exceptions.RequestException as e:
            if retry < Config.MAX_RETRIES - 1:
                app.logger.warning(f"{error_prefix}网络请求异常：{str(e)}，正在重试 ({retry + 1}/{Config.MAX_RETRIES})")
                continue
            else:
                error_msg = f"{error_prefix}网络请求异常：{str(e)}"
                app.logger.error(error_msg)
                return None, error_msg
        except Exception as e:
            error_msg = f"{error_prefix}系统错误：{str(e)}"
            app.logger.error(error_msg)
            return None, error_msg
    return None, f"{error_prefix}：未知错误或所有重试均失败"

feishu_token_cache = {'token': None, 'expire_time': 0}

def get_feishu_token():
    global feishu_token_cache

    if feishu_token_cache['token'] and time.time() < feishu_token_cache['expire_time']:
        app.logger.info("从缓存获取飞书访问令牌")
        return feishu_token_cache['token']

    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }
    request_body = {
        "app_id": app.config['FEISHU_APP_ID'],
        "app_secret": app.config['FEISHU_APP_SECRET']
    }
    
    app.logger.info(f"正在请求飞书访问令牌 - app_id: {app.config['FEISHU_APP_ID']}")
    result, error = _make_api_request(
        'post',
        Config.FEISHU_AUTH_URL,
        headers=headers,
        json_data=request_body,
        error_prefix="获取飞书访问令牌"
    )

    if error:
        return None
    
    # 检查API响应状态
    if result.get('code', -1) == 0:
        token = result.get('tenant_access_token')
        if token:
            app.logger.info("成功获取飞书访问令牌")
            feishu_token_cache['token'] = token
            feishu_token_cache['expire_time'] = time.time() + 3600  # 假设令牌有效期为1小时
            return token
        else:
            app.logger.error("获取飞书访问令牌失败：响应中不包含 access_token")
            return None
    else:
        app.logger.error(f"获取飞书访问令牌失败：{result.get('msg', '未知错误')}")
        return None

        


def get_node_token(token, node_token):
    """获取知识空间节点信息"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    url = f"{Config.FEISHU_API_BASE_URL}/wiki/v2/spaces/get_node"
    params = {
        "token": node_token,
        "obj_type": "wiki"
    }

    app.logger.info(f"正在获取节点信息 - URL: {url}, params: {params}")
    result, error = _make_api_request(
        'get',
        url,
        headers=headers,
        params=params,
        error_prefix="获取知识空间节点信息"
    )

    if error:
        return None, error

    node_info = result.get('data', {})
    obj_token = node_info.get('node', {}).get('obj_token')
    if obj_token:
        app.logger.info(f"成功获取节点信息 - obj_token: {obj_token}")
        return obj_token, None
    else:
        error_msg = "获取节点信息失败：响应中不包含 obj_token"
        app.logger.error(error_msg)
        return None, error_msg

def get_table_records():
    """获取飞书多维表格记录"""
    token = get_feishu_token()
    if not token:
        return [], "无法获取飞书访问令牌"

    node_token = app.config['FEISHU_BASE_ID']
    app_token, error = get_node_token(token, node_token)
    if error:
        return [], error
    
    table_id = app.config['FEISHU_TABLE_ID']

    # 检查多维表格参数是否有效
    if not app_token or not table_id:
        app.logger.error("多维表格参数无效")
        return [], "配置错误：多维表格参数无效"
    
    app.logger.info(f"正在获取多维表格数据 - app_token: {app_token}, table_id: {table_id}")
    
    # 设置请求头
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # 构建多维表格API请求URL
    url = f"{Config.FEISHU_BITABLE_URL}/apps/{app_token}/tables/{table_id}/records"
    params = {
        "page_size": 20
    }
    
    app.logger.info(f"请求URL: {url}")
    
    result, error = _make_api_request(
        'get',
        url,
        headers=headers,
        params=params,
        error_prefix="获取飞书多维表格记录"
    )

    if error:
        return [], error

    items = result.get('data', {}).get('items', [])
    app.logger.info(f"成功获取多维表格数据：{len(items)}条记录")
    return items, None
        



def get_article_fields(record):
    """从记录中提取字段数据"""
    if 'fields' in record:
        return record.get('fields', {})
    elif 'record' in record and 'fields' in record['record']:
        return record['record'].get('fields', {})
    return record

def process_article_content(content, is_preview=False):
    """处理文章内容"""
    if not content:
        return ''
    
    if is_preview:
        # 预览模式只返回前100个字符
        return content[:100] + '...' if len(content) > 100 else content
    else:
        # 完整模式将Markdown转换为安全的HTML
        # 确保 content 是字符串类型
        content_str = str(content)
        app.logger.debug(f"process_article_content: Input to markdown: type={type(content_str)}, value={content_str[:200]}...") # Log first 200 chars
        html_content = markdown(content_str)
        app.logger.debug(f"process_article_content: Output from markdown: type={type(html_content)}, value={html_content[:200]}...") # Log first 200 chars
        app.logger.debug(f"process_article_content: html_content type after markdown: {type(html_content)}")
        app.logger.debug(f"process_article_content: Input to clean: type={type(html_content)}, value={html_content[:200]}...")
        if isinstance(html_content, list):
            html_content = str(html_content) # Convert list to string if it's a list
            app.logger.debug(f"process_article_content: Converted html_content from list to string: type={type(html_content)}, value={html_content[:200]}...")
        
        cleaned_content = clean(
            html_content,
            tags=['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'br'],
            attributes={'*': ['class']},
            strip=True
        )
        app.logger.debug(f"process_article_content: Output from clean: type={type(cleaned_content)}, value={cleaned_content[:200]}...") # Log first 200 chars
        return cleaned_content

@app.route('/')
def index():
    app.logger.info("进入 index 路由")
    # 获取文章列表
    records, error = get_table_records()
    articles = []
    
    # 如果从API获取不到数据，返回错误信息
    if not records:
        app.logger.error(f"获取文章列表失败：{error}")
        return render_template('error.html', error=error), 500

    # 处理API返回的记录
    for i, record in enumerate(records):
        try:
            fields = get_article_fields(record)

            # 获取并处理内容
            raw_content = fields.get('概要内容输出', '')
            preview_content = process_article_content(raw_content, is_preview=True)

            # 清理和转义内容
            title_content = _convert_to_string(fields.get('标题', '无标题'))
            app.logger.debug(f"Clean input for title: type={type(title_content)}, value={title_content}")
            quote_content = _convert_to_string(fields.get('金句输出', ''))
            app.logger.debug(f"Clean input for quote: type={type(quote_content)}, value={quote_content}")
            comment_content = _convert_to_string(fields.get('黄叔点评', ''))
            app.logger.debug(f"Clean input for comment: type={type(comment_content)}, value={comment_content}")

            article = {
                'record_id': record.get('record_id'),  # 添加 record_id
                'title': clean(title_content, strip=True),
                'quote': clean(quote_content, strip=True),
                'comment': clean(comment_content, strip=True),
                'content': preview_content
            }

            # 确保标题字段有值
            if not article['title']:
                article['title'] = '无标题'
                app.logger.warning(f"记录 {i + 1} 没有标题，使用默认值")

            articles.append(article)
        except Exception as e:
            app.logger.error(f"处理记录 {i + 1} 时出错: {str(e)}")
            continue
    
    app.logger.info(f"成功处理 {len(articles)} 篇文章")
    return render_template('index.html', articles=articles)

@app.route('/article/<record_id>')
def article(record_id):
    app.logger.info(f"进入 article 路由，record_id: {record_id}")
    records, error = get_table_records()
    
    # 如果获取数据失败，返回错误信息
    if error:
        app.logger.error(f"获取文章数据失败：{error}")
        return render_template('error.html', error=error), 500
    
    # 查找匹配 record_id 的文章
    article = next((r for r in records if r.get('record_id') == record_id), None)

    if not article:
        error = "文章不存在"
        app.logger.error(f"未找到 record_id 为 {record_id} 的文章")
        return render_template('error.html', error=error), 404

    try:
        fields = get_article_fields(article)
        raw_content = fields.get('概要内容输出', '')
        app.logger.debug(f"处理文章 {record_id} 的 raw_content 数据类型: {type(raw_content)}")
        full_content = process_article_content(raw_content, is_preview=False)
        app.logger.debug(f"处理文章 {record_id} 的 full_content 数据类型: {type(full_content)}")

        title_content = _convert_to_string(fields.get('标题', '无标题'))
        app.logger.debug(f"Clean input for title: type={type(title_content)}, value={title_content}")
        quote_content = _convert_to_string(fields.get('金句输出', ''))
        app.logger.debug(f"Clean input for quote: type={type(quote_content)}, value={quote_content}")
        comment_content = _convert_to_string(fields.get('黄叔点评', ''))
        app.logger.debug(f"Clean input for comment: type={type(comment_content)}, value={comment_content}")

        article_data = {
            'title': clean(title_content, strip=True),
            'quote': clean(quote_content, strip=True),
            'comment': clean(comment_content, strip=True),
            'content': Markup(full_content)  # 使用 Markup 标记为安全HTML
        }

        raw_external_link = fields.get('链接', '')
        processed_external_link = None

        if isinstance(raw_external_link, dict):
            # Assuming the dictionary contains a 'url' key for the actual link
            processed_external_link = raw_external_link.get('url')
        elif isinstance(raw_external_link, str):
            processed_external_link = raw_external_link

        if processed_external_link:
            try:
                app.logger.info(f"尝试获取外部链接内容: {processed_external_link}")
                response = requests.get(processed_external_link, timeout=Config.REQUEST_TIMEOUT)
                response.raise_for_status()  # 检查HTTP错误
                article_data['external_html'] = Markup(response.text)  # 将外部HTML内容标记为安全HTML
                app.logger.info(f"成功获取外部链接内容: {processed_external_link}")
                article_data['content'] = Markup(response.text)  # 如果成功获取外部HTML，则将其设置为主要内容
            except requests.exceptions.RequestException as e:
                app.logger.error(f"获取外部链接内容失败: {processed_external_link} - {str(e)}")
                article_data['external_html'] = Markup(f"<p>无法加载外部内容: {str(e)}</p>")

        return render_template('detail.html', article=article_data)
    except Exception as e:
        error_msg = f"处理文章 {record_id} 时出错: {str(e)}"
        app.logger.error(error_msg)
        return render_template('error.html', error=error_msg), 500
    



if __name__ == '__main__':
    # 使用配置文件中的调试模式设置
    app.run(host='0.0.0.0', port=8082, debug=False)