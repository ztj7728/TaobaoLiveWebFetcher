## 项目简介
这是一个用于爬取淘宝直播间弹幕的项目。

## 
```bash
python main.py
【淘宝直播间】[529180182626]直播间：正在监听中.
【√】WebSocket连接成功.
【聊天msg】[0]tb579792624: 有啥礼品
【聊天msg】[0]tb579792624: [-哈哈哈]
【聊天msg】[0]tb579792624: 送钢化膜么
【聊天msg】[0]jiasheng0812: 14pro膜
【聊天msg】[0]tb579792624: 镜头膜不要
【聊天msg】[0]tb856805467: 必须在直播间主播弹的链接下单才🈶直播赠品，下完单必须回到直播间跟主播讲才有礼品未讲默认无礼品
【进场msg】[0]王v屋v清v源 进入了直播间
【进场msg】[0]tb131978656 进入了直播间
【统计msg】当前观看人数: 0, 累计观看人数: 867
【√】发送心跳包
【统计msg】当前观看人数: 0, 累计观看人数: 868
【√】发送心跳包
【统计msg】当前观看人数: 0, 累计观看人数: 870
【√】发送心跳包
【进场msg】[0]吉祥如意 进入了直播间
```

## 安装步骤

1. 克隆项目到本地：
   ```bash
   git clone https://github.com/ztj7728/TaobaoLiveWebFetcher.git
   cd TaobaoLiveWebFetcher
   ```

2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

3. 安装 Playwright 所需的浏览器：
   ```bash
   playwright install
   ```

4. 修改 `main.py` 中的直播间 ID 为你想要爬取的直播间 ID。

5. 运行程序：
   ```bash
   python main.py
   ```

## 项目结构
```
your-repository/
├── main.py            # 主程序
├── liveMan.py         # 逻辑程序
├── requirements.txt   # 项目依赖
└── README.md          # 项目说明文档
```

## 贡献

欢迎提交 Pull Request 和提出 Issues，贡献您的代码或反馈意见！
