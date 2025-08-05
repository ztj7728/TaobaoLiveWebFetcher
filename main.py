#!/usr/bin/python
# coding:utf-8

# @FileName:    main.py
# @Time:        2025/5/14 13:09
# @Author:      manwhatcanisay
# @Project:     taobaoLiveWebFetcher

import time
import queue
from liveMan import TaobaoLiveWebFetcher

if __name__ == '__main__':
    live_id = '529124645115'
    if not live_id:
        print("【X】错误：请在 main.py 中设置有效的 live_id")
    else:
        # 创建消息队列，与抖音版本保持一致
        message_queue = queue.Queue()
        fetcher = TaobaoLiveWebFetcher(live_id, message_queue)
        
        try:
            # Optional: Get initial status before starting continuous monitoring
            # fetcher.get_room_status() 
            fetcher.start()
            
            # 使用与抖音版本相同的消息处理逻辑
            print("【i】监听已启动。按 Ctrl+C 停止。")
            while True:
                try:
                    # 从队列中获取消息，超时时间1秒
                    message = message_queue.get(timeout=1.0)
                    
                    # 根据消息类型进行不同的处理
                    msg_type = message['type']
                    display_text = message['display_text']
                    
                    if msg_type == 'chat':
                        print(f"【聊天msg】{display_text}")
                    elif msg_type == 'gift':
                        print(f"【礼物msg】{display_text}")
                    elif msg_type == 'like':
                        print(f"【点赞msg】{display_text}")
                    elif msg_type == 'member':
                        print(f"【进场msg】{display_text}")
                    elif msg_type == 'social':
                        print(f"【关注msg】{display_text}")
                    elif msg_type == 'stat':
                        print(f"【统计msg】{display_text}")
                    elif msg_type == 'emoji':
                        print(f"【表情msg】{display_text}")
                    elif msg_type == 'control':
                        print(f"【控制msg】{display_text}")
                        # 如果是直播结束消息，可以选择退出
                        if message['data'].get('action') == 'end':
                            print("【i】直播已结束，停止监听。")
                            break
                    else:
                        print(f"【未知msg】{display_text}")
                        
                except queue.Empty:
                    # 队列为空，继续等待
                    continue
                except KeyboardInterrupt:
                    break

        except KeyboardInterrupt:
            print("\n【i】收到 Ctrl+C，正在停止...")
        except Exception as e:
            print(f"【X】主程序发生意外错误: {e}")
            # Optional: Log traceback for debugging
            # import traceback
            # traceback.print_exc()
        finally:
            print("【i】尝试停止...")
            fetcher.stop()
            print("【i】已停止。")
