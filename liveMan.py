#!/usr/bin/env python3
"""
淘宝直播间弹幕监听器 - 统一版本
统一接口风格，与抖音版本保持一致
"""
import re
import time
import json
import hashlib
import threading
import random
import requests
import base64
from urllib.parse import urlparse, parse_qs, unquote
from playwright.sync_api import sync_playwright


class ProtobufMessageParser:
    """protobuf+JSON混合格式消息解析器"""
    
    @staticmethod
    def parse_base64_message(base64_data):
        """解析base64编码的混合格式消息"""
        try:
            decoded_bytes = base64.b64decode(base64_data)
            json_objects = []
            current_pos = 0
            
            while current_pos < len(decoded_bytes):
                json_start = -1
                for i in range(current_pos, len(decoded_bytes)):
                    if decoded_bytes[i] == 0x7B:
                        json_start = i
                        break
                
                if json_start == -1:
                    break
                
                brace_count = 0
                in_string = False
                escaped = False
                json_end = -1
                
                for i in range(json_start, len(decoded_bytes)):
                    char = chr(decoded_bytes[i]) if decoded_bytes[i] < 128 else '?'
                    
                    if not in_string:
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                        elif char == '"':
                            in_string = True
                    else:
                        if escaped:
                            escaped = False
                        elif char == '\\':
                            escaped = True
                        elif char == '"':
                            in_string = False
                    
                    if brace_count == 0 and i > json_start:
                        json_end = i
                        break
                
                if json_end != -1:
                    json_bytes = decoded_bytes[json_start:json_end + 1]
                    json_string = json_bytes.decode('utf-8', errors='ignore')
                    
                    try:
                        json_obj = json.loads(json_string)
                        json_objects.append(json_obj)
                    except json.JSONDecodeError:
                        pass
                    
                    current_pos = json_end + 1
                else:
                    break
            
            return {'json_objects': json_objects, 'raw_bytes': decoded_bytes}
            
        except Exception as e:
            print(f"【X】解析protobuf消息失败: {e}")
            return None


class TaobaoLiveWebFetcher:
    
    def __init__(self, live_id):
        """
        淘宝直播间弹幕抓取对象
        :param live_id: 直播间的ID或URL
        """
        # 处理输入参数
        if 'taobao.com' in str(live_id):
            self.live_url = live_id
            match = re.search(r'liveId=(\d+)', live_id)
            self.live_id = match.group(1) if match else None
        else:
            self.live_id = str(live_id)
            self.live_url = f"https://tbzb.taobao.com/live?liveId={self.live_id}"

        self.user_agent = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/136.0.0.0 Safari/537.36'
        )

        self.topic = None
        self.cookie_dict = None
        self.session = None
        self.protobuf_parser = ProtobufMessageParser()

        # 连接控制
        self._stop_event = threading.Event()
        self._connection_thread = None
        self._heartbeat_thread = None
        self._reconnect_delay = 1
        self._max_reconnect_delay = 60
        self._pagination_ctx = None
        self._last_message_time = time.time()
        self._heartbeat_interval = 10
        self._no_message_timeout = 30

    def start(self):
        """启动监听"""
        self._stop_event.clear()
        self._reconnect_delay = 1
        print("【√】WebSocket连接成功.")  # 统一输出格式
        self._connection_thread = threading.Thread(target=self._run_connection_loop)
        self._connection_thread.daemon = True
        self._connection_thread.start()
        
        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """停止监听"""
        print("WebSocket connection closed.")  # 统一输出格式
        self._stop_event.set()
        if self._connection_thread and self._connection_thread.is_alive():
            self._connection_thread.join(timeout=5)
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)
        if self.session:
            self.session.close()

    def get_room_status(self):
        """获取直播间状态"""
        if not self.live_id:
            print("【X】无法获取直播间ID")
            return
        print(f"【淘宝直播间】[{self.live_id}]直播间：正在监听中.")

    def _run_connection_loop(self):
        """连接循环管理"""
        while not self._stop_event.is_set():
            try:
                self._connect_and_listen()
                if not self._stop_event.is_set():
                    self._handle_reconnect("连接结束")
                else:
                    break
            except Exception as e:
                if not self._stop_event.is_set():
                    self._handle_reconnect(f"错误: {e}")
                else:
                    break

    def _handle_reconnect(self, reason):
        """处理重连"""
        if self._stop_event.is_set():
            return
        self._stop_event.wait(timeout=self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    def _connect_and_listen(self):
        """连接和监听主逻辑"""
        try:
            self.topic, self.cookie_dict = self.get_topic_and_cookies()
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': self.user_agent})
            self.session.cookies.update(self.cookie_dict)
            
            # 启动心跳线程
            self._heartbeat_thread = threading.Thread(target=self._sendHeartbeat, daemon=True)
            self._heartbeat_thread.start()
            
            self._last_message_time = time.time()
            self._reconnect_delay = 1
            
            # 开始监听
            self._listen_comments()
            
        except Exception as e:
            raise

    def get_topic_and_cookies(self):
        """获取topic和cookies"""
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
            page.goto(self.live_url, timeout=15000)
            for _ in range(10):
                if topic:
                    break
                time.sleep(1)
            cookies = context.cookies()
            browser.close()

        if not topic:
            raise ValueError("【X】未能获取到topic")

        cookie_dict = {c['name']: c['value'] for c in cookies if c['name'] in ['_m_h5_tk', '_m_h5_tk_enc']}
        return topic, cookie_dict

    def make_sign(self, m_h5_tk, t, app_key, data_str):
        """生成签名"""
        token = m_h5_tk.split('_', 1)[0]
        s = f"{token}&{t}&{app_key}&{data_str}"
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def _sendHeartbeat(self):
        """发送心跳包 - 统一函数名"""
        url = "https://h5api.m.taobao.com/h5/mtop.taobao.powermsg.h5.msg.pullnativemsg/1.0/"
        app_key = "12574478"
        offset = str(int(time.time() * 1000))
        headers = {
            'x-biz-type': 'powermsg',
            'x-biz-info': 'namespace=1',
            'referer': f'https://tbzb.taobao.com/live?liveId={self.live_id}' if self.live_id else 'https://tbzb.taobao.com/'
        }

        while not self._stop_event.is_set():
            try:
                now = time.time()
                if now - self._last_message_time > self._no_message_timeout:
                    break

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

                timestamps = result.get('data', {}).get('timestampList', [])
                
                if timestamps:
                    offset = timestamps[-1].get('offset', offset)
                    for timestamp_data in timestamps:
                        self._parse_protobuf_message(timestamp_data)
                    self._last_message_time = time.time()
                    print("【√】发送心跳包")  # 统一输出格式

                time_to_wait = self._heartbeat_interval
                while time_to_wait > 0 and not self._stop_event.is_set():
                    sleep_duration = min(time_to_wait, 1.0)
                    woken_up = self._stop_event.wait(timeout=sleep_duration)
                    if woken_up:
                        break
                    time_to_wait -= sleep_duration

            except Exception as e:
                if self._stop_event.is_set():
                    break
                self._stop_event.wait(timeout=5)

    def _parse_protobuf_message(self, timestamp_data):
        """解析protobuf消息"""
        try:
            data_b64 = timestamp_data.get('data', '')
            if not data_b64:
                return
            
            parsed_result = self.protobuf_parser.parse_base64_message(data_b64)
            if not parsed_result:
                return
            
            for json_obj in parsed_result['json_objects']:
                self._process_message(json_obj)
                
        except Exception as e:
            pass

    def _process_message(self, json_obj):
        """处理消息 - 统一接口"""
        try:
            if not isinstance(json_obj, dict):
                return
            
            # 统计信息消息
            if 'viewCountFormat' in json_obj or 'pageViewCount' in json_obj:
                self._parseRoomUserSeqMsg(json_obj)
            # 用户进入消息
            elif 'nick' in json_obj and ('flowSourceText' in json_obj or 'subType' in json_obj):
                self._parseMemberMsg(json_obj)
            # 点赞消息
            elif 'value' in json_obj and 'dig' in json_obj.get('value', {}):
                self._parseLikeMsg(json_obj)
            # 其他消息类型
            elif 'subType' in json_obj:
                sub_type = json_obj.get('subType', 0)
                if sub_type == 10001:
                    self._parseChatMsg(json_obj)
                elif sub_type == 10002:
                    self._parseGiftMsg(json_obj)
                    
        except Exception as e:
            pass

    def _listen_comments(self):
        """监听评论"""
        while not self._stop_event.is_set():
            try:
                res = self.fetch_comments()
                data = res.get('data', {})
                self._pagination_ctx = data.get('paginationContext')
                comments = data.get('comments', [])
                
                if comments:
                    self._last_message_time = time.time()
                
                for c in comments:
                    self._parseChatMsg(c)
                
                delay = int(data.get('delay', 6000)) / 1000
                for _ in range(int(delay)):
                    if self._stop_event.is_set(): 
                        break
                    time.sleep(1)
                    
            except Exception as e:
                if not self._stop_event.is_set():
                    raise

    def fetch_comments(self):
        """获取评论"""
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

    # 统一的消息解析函数 - 与抖音版本命名一致
    def _parseChatMsg(self, payload):
        """聊天消息"""
        # 检查数据来源并正确提取字段
        if 'publisherNick' in payload:
            # 来自评论API的消息
            nick = payload.get('publisherNick', '匿名')
            user_id = payload.get('publisherId', '0')
            content = payload.get('content', '')
        else:
            # 来自protobuf的消息
            nick = payload.get('nick', '匿名')
            user_id = payload.get('userid', payload.get('userId', '0'))
            content = payload.get('content', payload.get('text', ''))
        
        if content and not self._is_gift_message(content):
            print(f"【聊天msg】[{user_id}]{nick}: {content}")

    def _parseGiftMsg(self, payload):
        """礼物消息"""
        if isinstance(payload, dict):
            nick = payload.get('nick', payload.get('userName', '匿名'))
            gift_name = payload.get('giftName', payload.get('itemName', '未知礼物'))
            gift_count = payload.get('count', payload.get('num', 1))
        else:
            # 从评论中解析礼物
            nick = payload.get('publisherNick', '匿名')
            content = payload.get('content', '')
            gift_name, gift_count = self._extract_gift_info(content)
        
        print(f"【礼物msg】{nick} 送出了 {gift_name}x{gift_count}")

    def _parseLikeMsg(self, payload):
        """点赞消息"""
        if 'value' in payload:
            dig_count = payload.get('value', {}).get('dig', 1)
            print(f"【点赞msg】匿名用户 点了{dig_count}个赞")
        else:
            count = payload.get('count', 1)
            nick = payload.get('nick', '匿名用户')
            print(f"【点赞msg】{nick} 点了{count}个赞")

    def _parseMemberMsg(self, payload):
        """进入直播间消息"""
        nick = payload.get('nick', '匿名')
        user_id = payload.get('userid', payload.get('userId', '0'))
        
        # 获取用户身份信息
        identify = payload.get('identify', {})
        is_vip = identify.get('VIP_USER', '0') == '1'
        is_member = payload.get('isMember', 'false') == 'true'
        fan_level = self._safe_int_convert(identify.get('fanLevel', 0))
        
        # 构建身份标识
        badges = []
        if is_vip:
            badges.append('VIP')
        if is_member:
            badges.append('会员')
        if fan_level > 0:
            badges.append(f'粉丝{fan_level}级')
        
        badge_str = '[' + ','.join(badges) + ']' if badges else ''
        print(f"【进场msg】[{user_id}]{badge_str}{nick} 进入了直播间")

    def _parseRoomUserSeqMsg(self, payload):
        """直播间统计"""
        current = payload.get('onlineCount', payload.get('current_viewers', 0))
        total = payload.get('totalCount', payload.get('total_viewers', 0))
        print(f"【统计msg】当前观看人数: {current}, 累计观看人数: {total}")

    def _parseSocialMsg(self, payload):
        """关注消息"""
        nick = payload.get('nick', payload.get('user_name', '匿名'))
        user_id = payload.get('userid', payload.get('user_id', '0'))
        print(f"【关注msg】[{user_id}]{nick} 关注了主播")

    def _parseFansclubMsg(self, payload):
        """粉丝团消息"""
        content = payload.get('content', '粉丝团消息')
        print(f"【粉丝团msg】 {content}")

    def _parseEmojiChatMsg(self, payload):
        """聊天表情包消息"""
        emoji_id = payload.get('emoji_id', '')
        user_name = payload.get('user', {}).get('nick_name', '匿名')
        print(f"【聊天表情包msg】{user_name} 发送了表情 {emoji_id}")

    def _parseControlMsg(self, payload):
        """直播间状态消息"""
        status = payload.get('status', 0)
        if status == 3:
            print("直播间已结束")
            self.stop()

    def _parseRoomStatsMsg(self, payload):
        """直播间统计信息"""
        display_long = payload.get('display_long', '')
        print(f"【直播间统计msg】{display_long}")

    def _parseRankMsg(self, payload):
        """直播间排行榜信息"""
        ranks_list = payload.get('ranks_list', [])
        print(f"【直播间排行榜msg】{ranks_list}")

    def _parseRoomMsg(self, payload):
        """直播间信息"""
        room_id = payload.get('common', {}).get('room_id', self.live_id)
        print(f"【直播间msg】直播间id:{room_id}")

    # 辅助函数
    def _safe_int_convert(self, value, default=0):
        """安全的整数转换"""
        try:
            if isinstance(value, str):
                return int(value) if value.isdigit() else default
            elif isinstance(value, (int, float)):
                return int(value)
            else:
                return default
        except (ValueError, TypeError):
            return default

    def _is_gift_message(self, content):
        """判断是否为礼物消息"""
        gift_keywords = ['送出了', '打赏了', '礼物', '小心心', '棒棒糖']
        return any(keyword in content for keyword in gift_keywords)

    def _extract_gift_info(self, content):
        """从评论中提取礼物信息"""
        gift_name = "未知礼物"
        gift_count = 1
        
        if "送出了" in content:
            parts = content.split("送出了")
            if len(parts) > 1:
                gift_info = parts[1].strip()
                # 提取数量
                import re
                count_match = re.search(r'(\d+)', gift_info)
                if count_match:
                    gift_count = int(count_match.group(1))
                gift_name = re.sub(r'\d+', '', gift_info).strip()
        
        return gift_name, gift_count
