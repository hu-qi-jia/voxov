# Redis

## 持久化

RDB 是定时快照，SAVE 命令阻塞主线程，BGSAVEfork 子进程执行。

## 主从复制

主节点写，从节点读，replication 是异步的。
