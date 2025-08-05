#!/usr/bin/env python3
"""
淘宝直播间弹幕监听器 - 优化版
根据给定淘宝直播间 URL 或 ID，自动化抓取 topic 和所需 Cookie，并监听输出弹幕。
使用 mtop.taobao.powermsg.h5.msg.pullnativemsg 接口进行心跳维护，支持长时间监听。
数据输出格式与抖音监听器保持一致，支持无痛接入。

依赖：requests, playwright
安装：
    pip install requests playwright
    playwright install

示例用法：
    # 使用 URL
    python liveMan.py https://tbzb.taobao.com/live?liveId=518876609326

    # 使用直播间 ID
    python liveMan.py 518876609326

    # 作为库使用
    from liveMan import TaobaoLiveWebFetcher
    fetcher = TaobaoLiveWebFetcher("518876609326")
    fetcher.start()
"""
import re
import time
import json
import argparse
import hashlib
import threading
import random
import requests
import queue
import logging
from urllib.parse import urlparse, parse_qs, unquote
from playwright.sync_api import sync_playwright


class TaobaoLiveWebFetcher:
    def __init__(self, live_url_or_id, message_queue=None):
        """
        淘宝直播间弹幕抓取对象
        :param live_url_or_id: 直播间的 URL 或 ID，例如：
            https://tbzb.taobao.com/live?liveId=518876609326 或 518876609326
        :param message_queue: Queue for输出解析后的弹幕消息。
        """
        # 处理输入参数，判断是 URL 还是纯 ID
        if 'taobao.com' in str(live_url_or_id):
            self.live_url = live_url_or_id
            match = re.search(r'liveId=(\d+)', live_url_or_id)
            self.live_id = match.group(1) if match else None
        else:
            self.live_id = str(live_url_or_id)
            self.live_url = f"https://tbzb.taobao.com/live?liveId={self.live_id}"

        self.message_queue = message_queue
        self.user_agent = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/136.0.0.0 Safari/537.36'
        )

        self.topic = None
        self.cookie_dict = None
        self.session = None

        # 断线重连与心跳维护 - 与抖音版本保持一致
        self._stop_event = threading.Event()
        self._connection_thread = None
        self._heartbeat_thread = None
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
        self._pagination_ctx = None
        self._last_message_time = time.time()
        self._heartbeat_interval = 10  # 心跳间隔
        self._no_message_timeout = 30  # 无消息超时时间

        # 配置日志
        self.logger = logging.getLogger(__name__)

    def start(self):
        """启动 WebSocket 连接和监控 - 与抖音版本保持一致的接口"""
        self._stop_event.clear()
        self._reconnect_delay = 1
        print("【i】开始监听淘宝直播弹幕...")
        self._connection_thread = threading.Thread(target=self._run_connection_loop)
        self._connection_thread.daemon = True
        self._connection_thread.start()
        return self

    def stop(self):
        """停止监听 - 与抖音版本保持一致的接口"""
        print("【i】正在停止监听...")
        self._stop_event.set()
        if self._connection_thread and self._connection_thread.is_alive():
            self._connection_thread.join(timeout=5)
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)
        if self.session:
            self.session.close()
        print("【X】监听已停止。")

    def get_room_status(self):
        """获取直播间状态 - 与抖音版本保持一致的接口"""
        if not self.live_id:
            print("【X】无法获取直播间ID，无法查询状态")
            return
        print(f"【i】直播间ID: {self.live_id}")
        # 可以在这里实现具体的状态查询逻辑
        print("【i】直播间状态查询功能待实现")

    def _run_connection_loop(self):
        """内部连接循环管理"""
        while not self._stop_event.is_set():
            try:
                self._connect_and_listen()
                if not self._stop_event.is_set():
                    print("【i】连接正常结束，尝试重连...")
                    self._handle_reconnect("连接正常结束")
                else:
                    break
            except Exception as e:
                print(f"【X】连接或运行时发生错误: {e}")
                if not self._stop_event.is_set():
                    self._handle_reconnect(f"未知错误: {e}")
                else:
                    break

        print("【i】连接循环已停止。")

    def _handle_reconnect(self, reason):
        """处理重连等待期"""
        if self._stop_event.is_set():
            print("【i】停止事件已设置，取消重连。")
            return

        print(f"【i】连接因 '{reason}' 中断。将在 {self._reconnect_delay} 秒后尝试重连...")
        self._stop_event.wait(timeout=self._reconnect_delay)
        if self._stop_event.is_set():
            print("【i】等待重连时收到停止信号，取消重连。")
            return

        # 指数退避
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
        print("【i】正在尝试重连...")

    def _connect_and_listen(self):
        """连接和监听的主要逻辑"""
        try:
            print("【i】正在获取直播间参数...")
            self.topic, self.cookie_dict = self.get_topic_and_cookies()
            print(f"【√】成功获取直播间参数: topic={self.topic}")
            
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': self.user_agent})
            self.session.cookies.update(self.cookie_dict)
            
            # 启动心跳线程
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_powermsg, daemon=True)
            self._heartbeat_thread.start()
            print("【√】心跳线程已启动")
            
            # 重置最后消息时间
            self._last_message_time = time.time()
            self._reconnect_delay = 1  # 重置重连延迟
            
            # 开始监听评论
            self._listen_comments()
            
        except Exception as e:
            print(f"【X】连接过程出错: {e}")
            raise

    def get_topic_and_cookies(self):
        """使用 Playwright 渲染并拦截请求，提取 topic 并获取必要 Cookie。"""
        topic = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.user_agent)

            def handle_request(request):
                nonlocal topic
                url = request.url
                if 'mtop.taobao.iliad.comment.query.latest' in url and not topic:
                    qs = parse_qs(urlparse(url).query)
                    data_str = qs.get('data', [''])[0]
                    try:
                        data = json.loads(unquote(data_str))
                        topic = data.get('topic')
                    except:
                        pass

            context.on('request', handle_request)
            page = context.new_page()
            print(f"【i】正在访问直播间: {self.live_url}")
            page.goto(self.live_url, timeout=15000)
            for _ in range(10):
                if topic:
                    break
                time.sleep(1)
            cookies = context.cookies()
            browser.close()

        if not topic:
            raise ValueError("【X】未能从请求中拦截到 topic")

        cookie_dict = {c['name']: c['value'] for c in cookies if c['name'] in ['_m_h5_tk', '_m_h5_tk_enc']}
        if '_m_h5_tk' not in cookie_dict or '_m_h5_tk_enc' not in cookie_dict:
            raise ValueError("【X】缺少 _m_h5_tk 或 _m_h5_tk_enc Cookie")
        return topic, cookie_dict

    def make_sign(self, m_h5_tk, t, app_key, data_str):
        token = m_h5_tk.split('_', 1)[0]
        s = f"{token}&{t}&{app_key}&{data_str}"
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def fetch_comments(self):
        app_key = '34675810'
        t = str(int(time.time() * 1000))
        payload = {"topic": self.topic, "limit": 20, "tab": 2, "order": "asc"}
        if self._pagination_ctx:
            payload["paginationContext"] = self._pagination_ctx
        data_str = json.dumps(payload, separators=(',', ':'))
        sign = self.make_sign(self.session.cookies.get('_m_h5_tk', ''), t, app_key, data_str)
        params = {
            'jsv': '2.7.2', 'appKey': app_key, 't': t, 'sign': sign,
            'api': 'mtop.taobao.iliad.comment.query.latest', 'v': '1.0',
            'preventFallback': 'true', 'type': 'jsonp', 'dataType': 'jsonp',
            'callback': f'mtopjsonp{random.randint(1,100)}', 'data': data_str
        }
        url = 'https://h5api.m.taobao.com/h5/mtop.taobao.iliad.comment.query.latest/1.0/'
        r = self.session.get(url, params=params, timeout=10)
        json_str = r.text[r.text.find('(')+1:r.text.rfind(')')]
        return json.loads(json_str)

    def _heartbeat_powermsg(self):
        """心跳线程 - 增加连接状态检查"""
        url = "https://h5api.m.taobao.com/h5/mtop.taobao.powermsg.h5.msg.pullnativemsg/1.0/"
        app_key = "12574478"
        offset = str(int(time.time() * 1000))
        headers = {
            'x-biz-type': 'powermsg',
            'x-biz-info': 'namespace=1',
            'referer': f'https://tbzb.taobao.com/live?liveId={self.live_id}' if self.live_id else 'https://tbzb.taobao.com/'
        }

        print("【i】心跳线程已启动。")
        while not self._stop_event.is_set():
            try:
                # 检查连接是否失效（类似抖音版本的逻辑）
                now = time.time()
                if now - self._last_message_time > self._no_message_timeout:
                    print(f"【!】超过 {self._no_message_timeout} 秒未收到消息，连接可能已失效")
                    break  # 退出心跳线程，让主循环处理重连

                t = str(int(time.time() * 1000))
                data = {
                    "topic": self.topic,
                    "offset": offset,
                    "pagesize": 10,
                    "tag": "",
                    "bizcode": 1,
                    "sdkversion": "h5_3.4.2",
                    "role": 3
                }
                data_str = json.dumps(data, separators=(',', ':'))
                sign = self.make_sign(self.session.cookies.get('_m_h5_tk', ''), t, app_key, data_str)
                params = {
                    'jsv': '2.7.2', 'appKey': app_key, 't': t, 'sign': sign,
                    'api': 'mtop.taobao.powermsg.h5.msg.pullnativemsg', 'v': '1.0',
                    'preventFallback': 'true', 'type': 'jsonp', 'dataType': 'jsonp',
                    'callback': f'mtopjsonp{random.randint(1,100)}', 'data': data_str
                }

                resp = self.session.get(url, params=params, headers=headers, timeout=10)
                text = resp.text
                json_str = text[text.find('(')+1:text.rfind(')')]
                result = json.loads(json_str)

                ret0 = result.get('ret', ['未知'])[0]
                success = ret0.startswith('SUCCESS')
                old_offset = offset
                timestamps = result.get('data', {}).get('timestampList', [])
                if timestamps:
                    offset = timestamps[-1].get('offset', offset)

                if success and timestamps:
                    print(f"【心跳】收到 {len(timestamps)} 条消息通知，offset: {old_offset} -> {offset}")
                    # 更新最后消息时间
                    self._last_message_time = time.time()
                else:
                    print(f"【心跳】状态: {'成功' if success else '失败'} - {ret0}")

                # 使用与抖音版本相同的等待逻辑
                time_to_wait = self._heartbeat_interval
                while time_to_wait > 0 and not self._stop_event.is_set():
                    sleep_duration = min(time_to_wait, 1.0)
                    woken_up = self._stop_event.wait(timeout=sleep_duration)
                    if woken_up:
                        break
                    time_to_wait -= sleep_duration

            except Exception as e:
                print(f"【X】心跳请求失败: {e}")
                if self._stop_event.is_set():
                    break
                self._stop_event.wait(timeout=5)

        print("【i】心跳线程已停止。")

    def _listen_comments(self):
        """监听评论 - 优化数据输出格式"""
        while not self._stop_event.is_set():
            try:
                res = self.fetch_comments()
                data = res.get('data', {})
                self._pagination_ctx = data.get('paginationContext')
                comments = data.get('comments', [])
                
                if comments:
                    print(f"【i】收到 {len(comments)} 条新消息")
                    # 更新最后消息时间
                    self._last_message_time = time.time()
                
                for c in comments:
                    self._parse_comment_message(c)
                
                delay = int(data.get('delay', 6000)) / 1000
                for _ in range(int(delay)):
                    if self._stop_event.is_set(): 
                        break
                    time.sleep(1)
                    
            except Exception as e:
                print(f"【X】获取弹幕失败: {e}")
                if not self._stop_event.is_set():
                    print(f"【i】将在 {self._reconnect_delay} 秒后尝试重连...")
                    raise  # 让上层处理重连逻辑
                    
        print("【i】评论监听线程已停止。")

    def _parse_comment_message(self, comment):
        """解析评论消息 - 统一输出格式与抖音版本保持一致"""
        try:
            nick = comment.get('publisherNick', '匿名')
            content = comment.get('content', '')
            user_id = comment.get('publisherId', '')
            
            # 检查是否为礼物消息（淘宝直播中礼物信息可能包含在评论中）
            if self._is_gift_message(content):
                self._parse_gift_from_comment(comment, nick, user_id, content)
            else:
                # 普通聊天消息 - 与抖音格式完全一致
                display_text = f"{nick}: {content}"
                output_data = {
                    "type": "chat",
                    "data": {
                        "user_id": user_id,
                        "user_name": nick,
                        "content": content
                    },
                    "display_text": display_text
                }
                
                if self.message_queue:
                    self.message_queue.put(output_data)
                else:
                    print(f"【聊天msg】{display_text}")
                    
        except Exception as e:
            print(f"【X】解析评论消息时出错: {e}")

    def _is_gift_message(self, content):
        """判断是否为礼物消息"""
        gift_keywords = ['送出了', '打赏了', '礼物', '小心心', '棒棒糖', '点赞']
        return any(keyword in content for keyword in gift_keywords)

    def _parse_gift_from_comment(self, comment, user_name, user_id, content):
        """从评论中解析礼物信息 - 输出格式与抖音保持一致"""
        # 尝试从内容中提取礼物信息
        gift_name = "未知礼物"
        gift_count = 1
        
        # 简单的礼物解析逻辑（可根据实际情况优化）
        if "送出了" in content:
            parts = content.split("送出了")
            if len(parts) > 1:
                gift_info = parts[1].strip()
                # 尝试提取数量
                import re
                count_match = re.search(r'(\d+)', gift_info)
                if count_match:
                    gift_count = int(count_match.group(1))
                gift_name = re.sub(r'\d+', '', gift_info).strip()
        
        display_text = f"{user_name} 送出了 {gift_name}x{gift_count}"
        output_data = {
            "type": "gift",
            "data": {
                "user_name": user_name,
                "gift_name": gift_name,
                "count": gift_count
            },
            "display_text": display_text
        }
        
        if self.message_queue:
            self.message_queue.put(output_data)
        else:
            print(f"【礼物msg】{display_text}")

    def _parse_system_message(self, message_type, data):
        """解析系统消息 - 保持与抖音格式一致"""
        if message_type == "member_enter":
            # 用户进入直播间
            user_name = data.get('user_name', '未知用户')
            user_id = data.get('user_id', '')
            display_text = f"{user_name} 进入了直播间"
            output_data = {
                "type": "member",
                "data": {
                    "user_id": user_id,
                    "user_name": user_name,
                    "gender": "未知"  # 淘宝可能没有性别信息
                },
                "display_text": display_text
            }
            
        elif message_type == "like":
            # 点赞消息
            user_name = data.get('user_name', '未知用户')
            count = data.get('count', 1)
            display_text = f"{user_name} 点了{count}个赞"
            output_data = {
                "type": "like",
                "data": {
                    "user_name": user_name,
                    "count": count
                },
                "display_text": display_text
            }
            
        elif message_type == "follow":
            # 关注消息
            user_name = data.get('user_name', '未知用户')
            user_id = data.get('user_id', '')
            display_text = f"{user_name} 关注了主播"
            output_data = {
                "type": "social",
                "data": {
                    "user_id": user_id,
                    "user_name": user_name
                },
                "display_text": display_text
            }
            
        elif message_type == "room_stats":
            # 直播间统计
            current = data.get('current_viewers', 0)
            total = data.get('total_viewers', 0)
            display_text = f"当前观看人数: {current}, 累计观看人数: {total}"
            output_data = {
                "type": "stat",
                "data": {
                    "current_viewers": current,
                    "total_viewers": total
                },
                "display_text": display_text
            }
            
        else:
            return  # 未知消息类型，忽略
            
        if self.message_queue:
            self.message_queue.put(output_data)
        else:
            print(f"【系统msg】{display_text}")


def main():
    parser = argparse.ArgumentParser(description='淘宝直播弹幕监听器')
    parser.add_argument('live_url_or_id', help='直播间 URL 或 ID，例如 https://tbzb.taobao.com/live?liveId=... 或 518876609326')
    args = parser.parse_args()

    message_queue = queue.Queue()
    fetcher = TaobaoLiveWebFetcher(args.live_url_or_id, message_queue)
    try:
        fetcher.start()
        while True:
            try:
                message = message_queue.get(timeout=1.0)
                print(f"【收到消息】: {message['display_text']}")
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                break
    except KeyboardInterrupt:
        print("\n【i】收到中断信号，停止监听...")
    finally:
        fetcher.stop()

if __name__ == '__main__':
    main()
