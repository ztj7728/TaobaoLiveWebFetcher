#!/usr/bin/python
# coding:utf-8

# @FileName:    main.py
# @Time:        2025/5/14 13:09
# @Author:      manwhatcanisay
# @Project:     taobaoLiveWebFetcher

import time
from liveMan import TaobaoLiveWebFetcher

if __name__ == '__main__':
    live_id = '525338516315'
    if not live_id:
        print("【X】错误：请在 main.py 中设置有效的 live_id")
    else:
        fetcher = TaobaoLiveWebFetcher(live_id)
        try:
            # Optional: Get initial status before starting continuous monitoring
            # fetcher.get_room_status() 
            fetcher.start()
            
            # Keep the main thread alive so daemon threads can run.
            # Exit gracefully on Ctrl+C (KeyboardInterrupt).
            print("【i】监听已启动。按 Ctrl+C 停止。")
            while True:
                time.sleep(1) # Keep main thread alive, checking every second

        except KeyboardInterrupt:
            print("\n【i】收到 Ctrl+C，正在停止...")
            fetcher.stop()
            print("【i】已停止。")
        except Exception as e:
            print(f"【X】主程序发生意外错误: {e}")
            # Optional: Log traceback for debugging
            # import traceback
            # traceback.print_exc()
            print("【i】尝试停止...")
            fetcher.stop() # Attempt to stop cleanly even on unexpected errors
            print("【i】已停止。")
