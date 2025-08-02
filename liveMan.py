#!/usr/bin/env python3
"""
淘宝直播间弹幕监听器
根据给定淘宝直播间 URL 或 ID，自动化抓取 topic 和所需 Cookie，并监听输出弹幕。
使用 mtop.taobao.powermsg.h5.msg.pullnativemsg 接口进行心跳维护，支持长时间监听。
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

        # 断线重连与心跳维护
        self._stop_event = threading.Event()
        self._connection_thread = None
        self._heartbeat_thread = None
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
        self._pagination_ctx = None

    # （以下方法保持不变）
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
                else:
                    print(f"【心跳】状态: {'成功' if success else '失败'} - {ret0}")

                time_to_wait = 10
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
        self._reconnect_delay = 1
        while not self._stop_event.is_set():
            try:
                res = self.fetch_comments()
                data = res.get('data', {})
                self._pagination_ctx = data.get('paginationContext')
                comments = data.get('comments', [])
                if comments:
                    print(f"【i】收到 {len(comments)} 条新消息")
                for c in comments:
                    nick = c.get('publisherNick', '匿名')
                    content = c.get('content', '')
                    user_id = c.get('publisherId', '')
                    display_text = f"{nick}: {content}"
                    output_data = {
                        "type": "chat",
                        "data": {"user_id": user_id, "user_name": nick, "content": content},
                        "display_text": display_text
                    }
                    if self.message_queue:
                        self.message_queue.put(output_data)
                    else:
                        print(f"【聊天msg】{display_text}")
                delay = int(data.get('delay', 6000)) / 1000
                for _ in range(int(delay)):
                    if self._stop_event.is_set(): break
                    time.sleep(1)
                self._reconnect_delay = 1
            except Exception as e:
                print(f"【X】获取弹幕失败: {e}")
                if not self._stop_event.is_set():
                    print(f"【i】将在 {self._reconnect_delay} 秒后尝试重连...")
                    self._stop_event.wait(timeout=self._reconnect_delay)
                    self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
        print("【i】评论监听线程已停止。")

    def _run_connection_loop(self):
        try:
            print("【i】正在获取直播间参数...")
            self.topic, self.cookie_dict = self.get_topic_and_cookies()
            print(f"【√】成功获取直播间参数: topic={self.topic}")
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': self.user_agent})
            self.session.cookies.update(self.cookie_dict)
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_powermsg, daemon=True)
            self._heartbeat_thread.start()
            print("【√】心跳线程已启动")
            self._listen_comments()
        except Exception as e:
            print(f"【X】连接循环出错: {e}")
            if not self._stop_event.is_set():
                print(f"【i】将在 {self._reconnect_delay} 秒后尝试重连...")
                self._stop_event.wait(timeout=self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
                if not self._stop_event.is_set():
                    self._run_connection_loop()

    def start(self):
        self._stop_event.clear()
        self._reconnect_delay = 1
        print("【i】开始监听淘宝直播弹幕...")
        self._connection_thread = threading.Thread(target=self._run_connection_loop)
        self._connection_thread.daemon = True
        self._connection_thread.start()
        return self

    def stop(self):
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
        if not self.live_id:
            print("【X】无法获取直播间ID，无法查询状态")
            return
        print(f"【i】直播间ID: {self.live_id}")
        print("【i】直播间状态查询功能待实现")


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
