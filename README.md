## 项目简介
这是一个用于爬取淘宝直播间弹幕的项目。

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
