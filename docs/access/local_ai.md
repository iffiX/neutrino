# 让本地 AI 工具操作你的系统

你不用额外配置，电脑上的 Claude Code 等 AI 工具就能通过运行命令操作你的每个系统。

AI 工具能在终端里运行命令，所以可以直接使用[终端命令](/access/terminal)和 [SSH 连接](/access/ssh)。退出码原样返回，所以 AI 工具能判断命令是否成功。

## 前提条件

这些命令都经过电脑客户端，所以客户端要保持运行。

- `nclient terminal exec` 需要 **终端** 权限，那个系统的 **终端** 标签要启用账户。
- `ssh`、`rsync` 需要 **SSH** 权限，还要按 [SSH 连接](/access/ssh)打开开关。`rsync` 要在两端都安装。

## 告诉 AI 工具有哪些系统

在 `CLAUDE.md` 或 `AGENTS.md` 里写上系统的名称和用途，比如：

```markdown
- my-computer：写代码用的台式机
- lab-gpu：运行实验用的显卡电脑，用 `ssh lab-gpu.nt` 连接
```

## AI 工具可用的命令

```bash
# 在其他系统上运行命令，退出码原样返回
nclient terminal exec lab-gpu -- nvidia-smi
ssh lab-gpu.nt nvidia-smi
# 传输文件、查询系统、使用应用
rsync -a data/ lab-gpu.nt:data/
nclient ssh list
nclient app use <应用>
```

`nclient app use` 会打印应用的本机地址，AI 工具用这个地址连接应用。

退出码原样返回。下面的命令在远端以 7 退出，本机读到的也是 7。

```bash
nclient terminal exec my-computer -- sh -c "exit 7"
echo $?
```

```text
7
```

## 限制 AI 工具的权限

AI 工具能做这个账户能做的一切，所以你要用权限限制它。

在面板的 **客户端** 页，为这台电脑单独设置权限，只勾选它需要访问的系统。你也可以只开放终端，不开放文件，或者相反，做法见[客户端](/hub/clients)。

如果你要在其他系统上打开 AI 会话，使用 [CloudCLI](/deploy/cloudcli)。
