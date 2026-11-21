# 配置文件

把 `config.example.yaml` 复制为 `config.yaml` 修改，重启生效。没有这个文件也能用，所有东西都可以在界面里配置；配置文件适合想把 AI 配置纳入版本管理、或者批量部署的场景。

配置文件位置可以用环境变量 `MAC_CONFIG` 指定。

> 产品曾用名 MultiAgentsControl，环境变量前缀沿用 `MAC_` 保持不变，已有部署不受影响。

## 结构

```yaml
server:          # 服务本身
local_access:    # 本地操作
providers:       # 模型渠道
agents:          # 智能体
```

### server

| 键 | 说明 |
| --- | --- |
| `host` | 监听地址。`0.0.0.0` 时局域网设备能连上，但仍要在「设置 → 访问与网络」里开启局域网访问才能打开控制台；`127.0.0.1` 仅本机 |
| `port` | 端口，默认 18760 |
| `token` | 访问口令，留空表示不需要 |
| `data_dir` | 数据库所在目录 |

同名的环境变量（`MAC_HOST` 等）优先于这里。

### local_access

本地操作的默认值（`enabled`、`workspace`、`approval`、`allow_outside_workspace`、`timeout`、`max_steps`）。这些在界面的「设置」页里都能改，在那里改过的项以界面为准，所以这一段完全可以不写。见 [本地操作](local-access.md)。

### providers

```yaml
providers:
  - id: ollama                      # 稳定的标识，agents 里用它引用
    name: 本机 Ollama
    protocol: ollama                # openai / openai_responses / anthropic / gemini / ollama
    base_url: http://localhost:11434
    api_key: env:OPENAI_API_KEY     # 可选。推荐写成 env:变量名
    default_model: qwen3:8b
    extra_headers: {}               # 可选，自建网关的额外请求头
    num_ctx: 8192                   # 可选，仅 ollama 协议：上下文长度，默认 8192
    timeout: 600                    # 可选：流式读取超时（秒），默认 600；深度思考模型吐字慢可调大
```

### agents

```yaml
agents:
  - id: chief
    name: 总管
    chief: true            # 总智能体，只能有一个
    no_tools: false        # true = 这个智能体永远不能提出本地操作请求
    auto_approve: false    # true = 它的本地操作不再询问（等同于「永久允许」）
    avatar: ph:Crown       # 留空用名字首字；ph:图标名 使用图标
    avatar_file: ./avatars/chief.png   # 可选：用图片做头像（PNG/JPG/WebP/GIF，140 KB 以内，相对配置文件的路径），优先于 avatar
    color: teal            # persimmon / rose / amber / olive / pine / teal / slate / plum
    provider: ollama       # 上面渠道的 id
    model: ""              # 留空用渠道的 default_model
    description: 一句话简介（总智能体靠它判断把任务派给谁）
    system_prompt: 角色设定
    temperature:           # 可选
    max_tokens:            # 可选
```

可用的头像图标：`Robot` `Brain` `Lightbulb` `MagnifyingGlass` `Target` `Wrench` `ChartBar` `PenNib` `BookOpen` `Scales` `Flask` `Palette` `Crown` `Code` `ShieldCheck` `Compass` `Megaphone` `Sparkle`。

## 同步规则

- 每次启动时，文件里声明的渠道和智能体会写入数据库，界面上带「配置文件」标记。
- 它们的内容以文件为准：在界面里改了，下次启动会被文件覆盖。
- 从文件里删掉的条目，下次启动时会从数据库移除。
- 在界面里手动创建的渠道和智能体不受影响，两者可以并存。
- 密钥直接写在文件里会以明文存进数据库；写成 `env:变量名` 则只保存变量名。

## 写错了会怎样

YAML 语法错误不会让服务起不来：启动窗口会打印出错原因，并按「没有配置文件」继续运行。使用了不支持的协议的渠道会被跳过并给出提示。
