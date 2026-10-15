# 用 CVAT 核验 YTVIS 掩码标注

本文以 `youtube_vis_dancetrack` 验证集中的 `dancetrack0004` 为例，介绍从创建 Project、导入逐帧标注，
到使用 SAM 修正已有掩码并导出的操作。先完成 [CVAT 与 SAM 安装](../INSTALL.md)，打开
<http://localhost:8080/> 并登录。

## 1. 准备图片与标注

CVAT 中的 **Project（项目）**统一管理标签，**Task（任务）**存放一组图片及其标注，
**Job（作业）**是实际打开的编辑页面。建议一个数据集建一个 Project，一个视频序列建一个 Task。

本例使用已经按视频拆分的 **COCO instances 逐帧标注**。图片与标注不包含在本仓库或 Docker 镜像中，
需要另行准备，目录如下：

```text
youtube_vis_dancetrack/
├── valid/
│   ├── pseudo_instances.json               # 原始 YTVIS 标注，不直接导入
│   ├── JPEGImages/
│   │   └── dancetrack0004/
│   │       ├── 00000001.jpg
│   │       └── ...
│   └── archives/
│       └── dancetrack0004.zip              # 上传图片用
└── annotations/
    ├── youtube_vis_dancetrack_valid_pseudo.json
    └── valid_pseudo/
        └── dancetrack0004.json             # 上传标注用
```

整体验证集 JSON 已拆分到 `annotations/valid_pseudo/`。图片 ZIP 与 JSON 必须属于同一个序列，
不要给单序列 Task 上传整个验证集的 JSON。本例包含 1,203 张图片，类别名称为 `pedestrian`。

已有匹配的 ZIP 时可直接使用。需要重新打包时，在终端设置数据集目录，再执行下面的命令；
将示例绝对路径替换成自己的路径：

```bash
export DATASET_ROOT="/absolute/path/to/youtube_vis_dancetrack"
export SEQUENCE="dancetrack0004"

python3 - <<'PY'
import json
import os
import zipfile
from pathlib import Path

root = Path(os.environ['DATASET_ROOT'])
sequence = os.environ['SEQUENCE']
annotation = root / 'annotations' / 'valid_pseudo' / f'{sequence}.json'
data = json.loads(annotation.read_text(encoding='utf-8'))
archive = root / 'valid' / 'archives' / f'{sequence}.zip'
archive.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as output:
    for image in data['images']:
        name = image['file_name']
        output.write(root / 'valid' / 'JPEGImages' / name, arcname=name)
print(f'{archive}: {len(data["images"])} images')
PY
```

ZIP 内应保留 `dancetrack0004/00000001.jpg` 这样的路径，与 JSON 的 `images[].file_name` 一致。
上述命令会读取软链接指向的真实图片内容，不会把软链接本身打进 ZIP。

## 2. 创建 Project 和标签

1. 点击顶部 **Projects**，点击 **＋ → Create new project**。
2. **Name** 填写 `YTVIS-DanceTrack-valid`。
3. 在 **Labels / Constructor** 中新增标签，名称填写 `pedestrian`，形状类型选择 **Any**。
   标签名称需要与 JSON 的 `categories[].name` 完全一致。
4. 为该标签添加以下两个属性，输入类型都选择 **Text**，默认值可留空；保持 **Mutable** 关闭。
5. 保存标签，点击 **Submit & Open**。

| 属性名 | 含义 | 示例值 |
| --- | --- | --- |
| `video_id` | 原始 YTVIS 视频 ID | `1` |
| `instance_id` | 该视频内的实例 ID | `1` |

这两个属性用于保留视频中的目标身份。标注 JSON 中应将它们放入 `attributes`，值使用字符串，例如：

```json
{"attributes": {"video_id": "1", "instance_id": "1"}}
```

仅放在 annotation 顶层的自定义 ID 不应作为往返导出的唯一依据。CVAT 界面中的对象编号也不等于
YTVIS 的 `instance_id`；同一个人在不同帧中的 CVAT 对象编号可以不同。

## 3. 在 Project 中创建 Task

1. 在项目内选择 **＋ → Create new task**，确认 **Project** 指向刚创建的项目。
2. **Name** 填写 `valid-dancetrack0004`，**Subset** 可填写 `valid`。
3. 标签沿用 Project 的 `pedestrian`，无需在 Task 中重新创建。
4. 在 **Select files / My computer** 上传 `valid/archives/dancetrack0004.zip`。
   这里上传图片 ZIP；标注 JSON 在下一步上传。
5. 在 **Advanced configuration** 中将 **Sorting method** 设为 **Lexicographical**。
   本例文件名已补零，因此这种排序与帧顺序一致。保持帧步长为 `1`，不跳帧、不裁剪帧范围。
6. **Segment size** 可设为 `200`、**Overlap** 设为 `0`，将长序列分成几个较小的 Job。
7. 点击 **Submit & Open**，等待图片处理完成。

打开任一 Job，先确认图片方向、尺寸和顺序正确。本例源文件 `00000001.jpg` 通常显示为 CVAT 第 `0` 帧；
帧编号从零开始属于正常情况。导入匹配仍以图片路径为依据，不要人为给文件名减一。

## 4. 导入已有标注

1. 回到 **Task 详情页**，打开 **Actions → Upload annotations**。
   部分界面将该入口标为 **Import annotations**。
2. 格式选择 **COCO 1.0**。
3. 上传 `annotations/valid_pseudo/dancetrack0004.json`，等待导入完成。
4. 打开一个 Job，检查人物掩码、标签，以及对象属性中的 `video_id`、`instance_id`。
5. 再抽查序列中段和末段，确认标注与图片没有错帧。

任务级导入会把该序列的标注分配到相应 Job。不要将完整序列 JSON 逐个重复导入每个 Job。
在已编辑的任务上重新导入可能覆盖现有标注；先导出备份，再决定是否重新导入。

若出现 `Unknown key: Matching variant not found`，核对输入是否为逐帧 COCO：
顶层应包含 `images`、`annotations`、`categories`；掩码 `segmentation` 应使用有效的 COCO 编码。
本例使用 `{"size": [height, width], "counts": "..."}` 形式的压缩 RLE，`counts` 是字符串，
`attributes` 中的两个 ID 也是字符串。`image_id`、`category_id`、坐标等数值字段仍应保持数值。
不要通过修改扩展名把原始 YTVIS 文件伪装成 COCO。

## 5. 用 SAM 修正已有目标

先打开一个 Job。SAM 会把已有掩码作为初始输入，并将结果写回同一个对象。

1. 单击右侧 **Objects** 列表中需要修正的掩码条目，也可在画布中选择。
   只选一个，确保它未锁定、未隐藏。
2. 单击左侧魔棒 **AI Tools**，切换到 **Interactors**，选择 **Segment Anything**。
3. 确认面板出现 **Refine object #…**，编号对应当前目标。没有这段提示时，先重新选中掩码。
4. 点击 **Interact**。在应该保留或补入的区域单击**鼠标左键**，添加正点；
   在误分到背景或其他人的区域单击**鼠标右键**，添加负点。
5. 每次加点后等待预览更新，检查轮廓、孔洞、相邻人物的边界。首次处理一帧通常更慢。
6. 结果满意后点击顶部 **Done**。它会更新原对象的掩码，保留对象身份、标签、属性和分组。
7. 不满意时按 **Esc** 取消，原标注保持不变。已经点击 Done 的修改可通过界面的 **Undo** 撤销。
8. 点击顶部 **Save** 或按 **Ctrl+S**，等待保存完成。

**Done 是确认本次修正，Save 才是保存作业。** 首次使用建议只修正一个目标，保存并刷新页面，
确认结果及两个 ID 属性仍然正确，再处理其余目标。

修正模式使用完整图片，并保留像素掩码；ROI、从框开始、转换为多边形的选项在此模式下不可用。
原目标在预览期间会暂时隐藏，取消后恢复。SAM 仅修正当前帧，不会自动修改相邻帧或传播实例 ID。

对于少量边缘像素，可使用掩码编辑工具的画笔和橡皮擦继续处理。对于漏标目标，先清除选择，
再使用 SAM 创建新掩码；确认其 `pedestrian` 标签，并手动填写正确的 `video_id` 和 `instance_id`。
同一视频内，同一人的实例 ID 应保持一致；新增人物使用未占用的实例 ID。

## 6. 逐帧核验与导出

按 Job 顺序查看各帧，重点检查漏标、重复标注、相邻人物粘连、遮挡边界和身份是否混淆。
每完成一段就保存。可以将完成的 Job 标为 **Completed**，以便区分进度；状态标记不代替保存。

完成一个序列后：

1. 保存所有已修改的 Job，回到该 **Task 详情页**。
2. 选择 **Actions → Export task dataset**，格式选择 **COCO 1.0**。
3. 已保留原图时关闭 **Save images**，只导出标注；需要完整交付数据集时再开启。
4. 等待导出请求完成；如跳转到 **Requests** 页面，在对应请求完成后下载 ZIP。
5. 将结果保存到独立目录，例如 `corrected/dancetrack0004/`，保留原始伪标注。
6. 解压检查 `annotations/` 下的 JSON，确认图片路径、掩码及两个 ID 属性仍然存在。
   先用一个小任务验证导出结果可重新导入，再批量处理其他序列。

COCO 导出仍然是逐帧标注，不会自动变回 YTVIS。需要 YTVIS 时，后处理应依据图片文件名、原始帧顺序及
`video_id + instance_id` 将逐帧掩码合并，恢复视频的 `length`、尺寸和每帧 `segmentations`；
未出现目标的帧填入对应的空值。不要直接把 COCO JSON 重命名为 `pseudo_instances.json`。

需要恢复整个 CVAT 项目结构时，另外使用 Project/Task 的 **Backup** 功能。它与用于训练或评估的
COCO 导出用途不同。

## 7. 常见问题

| 现象 | 处理 |
| --- | --- |
| 图片存在但标注找不到对应帧 | 对照 ZIP 内路径与 JSON 的 `file_name`，确认序列一致、未跳帧 |
| 导入后只有框或多边形 | 检查 `segmentation` 是否为预期的掩码 RLE，是否误用了检测标注文件 |
| `video_id` / `instance_id` 丢失 | 检查 Project 的同名 Text 属性及 JSON 的 `attributes`，再做小任务往返验证 |
| AI Tools 中没有 SAM | 按 [安装指南](../INSTALL.md#7-验证与使用) 检查 Nuclio 函数是否为 `ready` |
| 没有 `Refine object #…` | 确认选中单个 Mask，模型为 Segment Anything；多边形、框和多选不进入该模式 |
| Interact 无法点击 | 解锁并显示目标；确认当前 Job 可编辑、模型已加载 |
| 切换模型后结果异常 | 按 [SAM 配置说明](../serverless/pytorch/facebookresearch/sam/README.md) 检查 `cvat.json`，重启 SAM 后刷新网页 |

其他序列重复第 3～6 节即可；标签和属性继续沿用同一个 Project。
