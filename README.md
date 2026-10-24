# Curiosity Pet(好奇心伙伴)

A local, privacy-first voice learning companion for a bilingual 7-year-old, running entirely on a 16GB Mac mini.
一只运行在家用 Mac mini 上的本地 AI 学习宠物:孩子在 iPad 上用语音提问,语音识别、回答生成、资料检索、安全过滤、语音合成全部在本机完成。

- **提案、架构图、流程图**:[docs/PROPOSAL.md](docs/PROPOSAL.md)
- **规则(硬性约束、组件栈、阶段验收)**:[CLAUDE.md](CLAUDE.md)
- **决策记录与修订理由**:[docs/DECISIONS.md](docs/DECISIONS.md)
- **实测数据**:[evals/results/](evals/results/)

## 现状(v0.1)

| 能做什么 | 实测 |
|---|---|
| iPad 上点一下,对小猫说话,逐句播放并高亮回答 | 说完到开口中位数 2.3 秒(本机)/ 2.8 秒(经网页) |
| 用孩子提问的语言回答(中、英、混说) | 36/36 |
| 本地没有资料时,只把去掉个人信息的话题词发给维基百科,并说明出处 | 38 条语句隐私实测泄漏 0 |
| 英短蓝猫形象,四种状态;项圈小灯标明"程序" | |
| 161 项测试 | `uv run pytest` |

还没做:审核知识库、学习流程(追问、小活动、收藏)、守卫模型与家长页、讲故事与周报、launchd 部署。

## 隐私

孩子的声音、原话、会话历史、记忆、心情不离开这台机器。仓库里没有任何儿童数据、录音、数据库或密钥;
家长设置(联系方式、家人名字、黑名单)放在本机数据目录的 `settings.json`,不入库。详见 [docs/PROPOSAL.md](docs/PROPOSAL.md) 第 11 节。

## 运行

```bash
bash setup_mac_mini.sh                  # 依赖、模型、基线(Tailscale 需手动安装)
uv sync
uv run python scripts/convert_kokoro.py  # Kokoro v1.1-zh 权重本机转换
uv run pytest
uv run pet --text                        # 命令行打字对话;uv run pet 用麦克风
uv run pet-server                        # iPad 网页服务,再用 tailscale serve --bg 8730 提供 HTTPS
```

硬件:Mac mini M4,16GB。软件:macOS,Ollama,Python 3.12,uv,mlx-audio。
