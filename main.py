#!/usr/bin/python
# coding:utf-8

# @FileName:    main.py
# @Time:        2025/8/5 统一版
# @Author:      ztj7728
# @Project:     TaobaoLiveWebFetcher

from liveMan import TaobaoLiveWebFetcher

if __name__ == '__main__':
    live_id = '529180182626'
    room = TaobaoLiveWebFetcher(live_id)
    room.get_room_status()
    room.start()
