# FFmpeg 安装指南（Windows）

FFmpeg 是音频格式转换必需的依赖工具。

## 方法一：使用 winget（推荐）

```powershell
winget install Gyan.FFmpeg
```

安装完成后，**重新打开终端**即可。

## 方法二：手动安装

### 1. 下载
访问 https://github.com/BtbN/FFmpeg-Builds/releases

下载 `ffmpeg-master-latest-win64-gpl.zip`

### 2. 解压
解压到 `C:\ffmpeg`

目录结构应该是：
```
C:\ffmpeg\bin\ffmpeg.exe
C:\ffmpeg\bin\ffprobe.exe
```

### 3. 添加环境变量
1. 右键"此电脑" → 属性 → 高级系统设置 → 环境变量
2. 找到 Path 变量，编辑
3. 添加新条目：`C:\ffmpeg\bin`
4. 确定保存

### 4. 验证安装
重新打开终端，运行：
```powershell
ffmpeg -version
```

显示版本信息即表示安装成功。

## 方法三：使用 chocolatey

```powershell
choco install ffmpeg
```

## 转换功能说明

安装 FFmpeg 后，在 Chat 中可以：

```
你: 转换 wav 到 flac
助手: 🎵 音频格式转换预览
       可转换文件: 5 个
       预计节省: 150 MB
       
你: 确认转换
助手: ✅ 转换完成！
       • 总计: 5 个文件
       • 成功: 5 个
       • 失败: 0 个
```

## 为什么需要转换？

| 格式 | 元数据支持 | 封面支持 | 压缩率 | 推荐度 |
|------|----------|---------|--------|--------|
| **FLAC** | ✅ 完善 | ✅ 支持 | 50-60% | ⭐⭐⭐⭐⭐ |
| **WAV** | ❌ 无标准 | ❌ 不支持 | 100%（无压缩） | ⭐⭐ |

转换后：
- 节省 30-50% 磁盘空间
- 支持完整的元数据标签
- 支持专辑封面嵌入
- 音质完全无损（FLAC 是无损压缩）
