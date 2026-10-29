# 用 CVAT 核验 YTVIS 掩码标注

本文以 LongTrack 中的 `dancetrack0041__p1` 为例，使用本分支的 **YTVIS 1.0** 格式直接导入
轨迹标注、使用 SAM 精修掩码，再导出 YTVIS；原始 DanceTrack GT bbox 保持不变。
先完成 [CVAT 与 SAM 安装](../INSTALL.md)，打开
<http://localhost:8080/> 并登录。

## 1. 准备图片与标注

CVAT 中的 **Project（项目）**统一管理标签，**Task（任务）**存放一组图片及其标注，
**Job（作业）**是实际打开的编辑页面。建议一个数据集建一个 Project，一个视频序列建一个 Task。

图片与标注不包含在 Docker 镜像中，需要另行准备。本例目录如下：

```text
data/longtrack/
├── v3/
│   └── instances.json                     # 上传标注用，可以包含多个视频
└── youtube_vis_longtrack/valid/
    ├── JPEGImages/
    │   └── dancetrack0041__p1/
    │       ├── 00000001.jpg
    │       └── ...
    └── archives/
        └── dancetrack0041__p1.zip          # 上传图片用
```

本例包含 1,003 张图片，类别名称为 `person`。可以直接上传完整的 `v3/instances.json`，
导入器按 Task 的图片路径匹配其中唯一一个完整视频，无需拆分 JSON。
当前入口仅支持 **Task 级别的一段完整图片序列**；不自动建任务，不支持 Project/Job 级导入导出，
也不按 MP4 的帧位置推断匹配。

## 2. 创建 Project 和标签

1. 点击顶部 **Projects**，点击 **＋ → Create new project**。
2. **Name** 填写 `LongTrack-valid`。
3. 在 **Labels / Constructor** 中新增标签，名称填写 `person`，形状类型选择 **Any**。
   标签名称需要与 JSON 的 `categories[].name` 完全一致。
4. 保存标签，点击 **Submit & Open**。无需为视频 ID 或实例 ID 创建标签属性。

| 来源身份 | 含义 | 示例值 |
| --- | --- | --- |
| `video_id` | 原始 YTVIS `videos[].id` | `9` |
| `instance_id` | 原始 YTVIS `annotations[].id` | `55` |

YTVIS 导入器自动保存这两个 ID，可在对象 **Details** 中只读查看，无需手工填写或修改源 JSON。
这里的 `instance_id` 是原始轨迹标注的 `id`，不是 `source_track_id`。
CVAT 界面中的对象编号也不等于
`instance_id`；同一个人在不同帧中的 CVAT 对象编号可以不同。

## 3. 在 Project 中创建 Task

1. 在项目内选择 **＋ → Create new task**，确认 **Project** 指向刚创建的项目。
2. **Name** 填写 `valid-dancetrack0041__p1`，**Subset** 可填写 `valid`。
3. 标签沿用 Project 的 `person`，无需在 Task 中重新创建。
4. 在 **Select files / My computer** 上传 `dancetrack0041__p1.zip`。
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
2. 格式选择 **YTVIS 1.0**，使用替换导入。
3. 上传 `data/longtrack/v3/instances.json`，等待导入完成。
   也可上传只含一份标注 JSON 的 ZIP。
4. 打开一个 Job，检查人物掩码、标签，以及对象 Details 中的 `video_id`、`instance_id`。
5. 再抽查序列中段和末段，确认标注与图片没有错帧。

已有掩码以普通 CVAT Mask 导入；有 bbox 但 `segmentations` 对应项为 `null` 的帧以参考矩形
导入。本例 v3 中有 110 个这样的实例帧。掩码支持压缩或非压缩的 COCO RLE，不支持多边形列表。
视频信息、原始轨迹 ID、GT `bboxes` 和 `source_*` 元数据通过通用 Task 来源关联记录保存；
导入对象通过 Shape 来源关联保存原始身份。当前掩码仍由 CVAT 原有标注系统管理，
修改掩码或移动参考矩形都不会修改 YTVIS 导出的 GT bbox。

任务级导入会把该序列的标注分配到相应 Job。不要将完整序列 JSON 逐个重复导入每个 Job。
替换导入会清理旧的 Task 来源基线，成功导入 YTVIS 后建立新基线；导入失败会回滚。
因此，改用其他格式替换 Task 或其中某个 Job 的标注后，需要重新导入 YTVIS 才能使用该格式导出。
在已编辑的任务上重新导入会覆盖现有标注；先导出备份，再决定是否重新导入。

## 5. 查看掩码

在 **Appearance → Color by → Instance** 下，默认颜色按来源格式、视频 ID 和实例 ID 确定，
同一实例跨帧、跨 Job 和刷新页面后保持一致。不同实例仍可能因调色板颜色有限而同色。
对象 Details 中的来源 ID 只读；启用画布文字的 **ID** 显示时，也会显示这两个来源 ID。

打开 Job 后，建议逐帧检查掩码而非连续播放视频。
连续播放时可能出现图片正常切换、掩码尚未显示就进入下一帧的现象，只有当暂停后才显示完整。
这是因为掩码图片异步加载， 而播放器的画布就绪判断尚未等待它加载完成。

掩码遮挡原图、影响判断时，可以临时隐藏：
点击右侧 **Objects 列表顶部的眼睛图标**，显示或隐藏当前列表中的对象。
或使用快捷键进行切换。默认快捷键是依次按 **T**、**H**；仅对单个已选中的对象切换可按 **H**。

## 6. 用 SAM 修正已有目标

先打开一个 Job。SAM 会把已有掩码作为初始输入，并将结果写回同一个对象。

1. 单击右侧 **Objects** 列表中需要修正的掩码条目，也可在画布中选择。
   按 **A** 可启用 **Select objects**，从空白处拖出选择框；只有完整落入框内的目标会被选中。
   只选一个，确保它未锁定、未隐藏。再次按 **A** 返回 **Cursor**。
2. 单击左侧魔棒 **AI Tools**，切换到 **Interactors**，选择 **Segment Anything**。
3. 确认面板出现 **Refine object #…**，编号对应当前目标。没有这段提示时，先重新选中掩码。
4. 点击 **Interact** 或按 **S**。在应该保留或补入的区域单击**鼠标左键**，添加正点；
   在误分到背景或其他人的区域单击**鼠标右键**，添加负点。
5. 每次加点后等待预览更新，检查轮廓、孔洞、相邻人物的边界。首次处理一帧通常更慢。
6. 结果满意后点击顶部 **Done**。它会更新原对象的掩码，保留对象身份、标签、属性和分组。
7. 不满意时按 **Esc** 取消，原标注保持不变。已经点击 Done 的修改可通过界面的 **Undo** 撤销。
8. 点击顶部 **Save** 或按 **Ctrl+S**，等待保存完成。

**Done 是确认本次修正，Save 才是保存作业。** 首次使用建议只修正一个目标，保存并刷新页面，
确认结果及来源 ID 仍然正确，再处理其余目标。

选好 **Segment Anything** 后，后续目标可直接按 **A** 框选单个掩码，再按 **S** 开始修正，
无需重复打开 AI Tools 面板。交互期间重复按 **S** 不会结束或重置当前会话。
**A**、**S** 是默认快捷键，可在 **Settings → Shortcuts** 中修改 **Select objects** 和
**Start AI interaction**；在输入框中输入文字时不会触发这两个操作。

修正模式使用完整图片，并保留像素掩码；ROI、从框开始、转换为多边形的选项在此模式下不可用。
原目标在预览期间会暂时隐藏，取消后恢复。SAM 仅修正当前帧，不会自动修改相邻帧或传播实例 ID。

对于少量边缘像素，可按下一节的方法继续精修。补齐参考矩形对应的缺失掩码时，
选中该参考矩形，再打开 Segment Anything，确认出现 **Fill mask for object #…**。
按 **S** 开始并添加正负点；SAM 使用该框作为提示，点击 **Done** 后创建继承其来源身份和标签的 Mask，
无需填写 ID。参考矩形可保留，也可删除；导出会使用新 Mask。
再次选中该参考矩形时，若当前帧已有同一来源实例的 Mask，SAM 会转为精修该 Mask。
补齐后可按下一节使用刷子继续修边；直接从空白处新画的 Mask 没有来源关联，不能用于 YTVIS 导出。
同一目标同一帧只能有一个 Mask，重复 Mask 会阻止导出。

当前支持精修和补齐原有轨迹，不分配全新轨迹 ID，未关联或关联到其他视频、未知实例的对象会阻止导出。
删除 Mask 后导出该帧的 `segmentation` 和 `area` 为 `null`，原始 bbox 仍保留。

## 7. 精修掩码

对于 SAM 修正后仍不准确的边缘、孔洞或少量误分像素，可直接编辑已有 Mask：

1. 暂停播放，找到目标掩码，确认它未锁定、未隐藏。
2. 打开右侧对象条目的菜单，选择 **Edit**；也可在已激活的掩码上按住 **Shift** 并双击。
   从已有对象的 Edit 进入会修改该对象；左侧 **Draw new mask → Shape** 用于创建新对象。
3. 放大需要精修的区域，在刷子工具栏选择工具：

   | 工具 | 用途 | 默认快捷键 |
   | --- | --- | --- |
   | **Brush** | 补入缺失像素 | **Shift+1** |
   | **Eraser** | 擦除多余像素 | **Shift+2** |
   | **Polygon** | 用多边形区域补入像素 | **Shift+3** |
   | **Remove polygon selection** | 用多边形区域擦除像素 | **Shift+4** |

4. 将 **Brush size** 调小，最小支持 **1 像素**；也可按住 **Alt**，按住鼠标右键左右拖动调整大小。
   画笔和橡皮擦支持圆形、方形笔头。
5. 沿边缘补画或擦除，必要时点击工具栏 **Hide mask** 对照原图，再恢复显示检查结果。
6. 点击工具栏勾号 **Finish** 或使用快捷键 **N** 完成本次编辑，再点击顶部 **Save** 或按 **Ctrl+S** 保存作业。
   按 **Esc** 可取消当前编辑；编辑期间不能切换帧。

**Remove underlying pixels** 会在绘制或编辑当前掩码时，擦除其他掩码在相同位置的像素。
在掩码工具栏打开时，按 **Shift+Q** 可切换开启或关闭，也可点击工具栏的向下箭头落到横线按钮；
按钮高亮表示已开启。快捷键可在 **Settings → Shortcuts** 中修改。
只有需要联动调整重叠边界时才开启；独立精修当前目标时保持关闭。
上述编辑只影响当前帧，不会自动传播到其他帧。

## 8. 逐帧核验与导出

按 Job 顺序查看各帧，重点检查漏标、重复标注、相邻人物粘连、遮挡边界和身份是否混淆。
每完成一段就保存。可以将完成的 Job 标为 **Completed**，以便区分进度；状态标记不代替保存。

完成一个序列后：

1. 保存所有已修改的 Job，回到该 **Task 详情页**。
2. 选择 **Actions → Export task dataset**，格式选择 **YTVIS 1.0**。
3. 已保留原图时关闭 **Save images**，只导出标注；需要完整交付数据集时再开启。
4. 等待导出请求完成；如跳转到 **Requests** 页面，在对应请求完成后下载 ZIP。
5. 将结果保存到独立目录，例如 `corrected/dancetrack0041__p1/`，保留原始标注。
6. 解压检查 `annotations/instances.json`，确认视频 ID、轨迹 ID、图片路径和 GT bbox 保持不变。
   先用一个小任务验证导出结果可重新导入，再批量处理其他序列。

导出会聚合所有 Job，按原视频顺序写出轨迹级 `segmentations` 和重新计算的 `areas`，保留
原始 `bboxes`、视频信息和来源元数据。结果只包含当前 Task 对应的视频，合回完整数据集时应按
`video_id` 替换该视频及其标注，保留其他视频。启用 **Save images** 时，图片位于 ZIP 的
`images/<原始 file_name>` 下。

需要恢复整个 CVAT 项目结构时，另外使用 Project/Task 的 **Backup** 功能。它与用于训练或评估的
YTVIS 导出用途不同；Task 关联的原始信息也会随备份恢复。

## 9. 常见问题

| 现象 | 处理 |
| --- | --- |
| 导入提示需要完整视频 | 对照 ZIP 内路径与 `videos[].file_names`，确认目录前缀、帧数、尺寸一致，未跳帧或删除帧 |
| 导入后部分目标只有框 | 源数据对应帧缺失 mask；选中参考矩形，通过 SAM 补齐并自动继承来源身份 |
| 导出提示身份错误或重复 Mask | 从参考矩形使用 SAM 补齐，删除未关联的独立 Mask 或同一帧同一实例的多余 Mask |
| 格式列表没有 YTVIS 1.0 | 更新后端及 worker 镜像，执行数据库迁移至 `0111_ann_sources`，刷新页面 |
| AI Tools 中没有 SAM | 按 [安装指南](../INSTALL.md#7-验证与使用) 检查 Nuclio 函数是否为 `ready` |
| 没有 `Refine object #…` 或 `Fill mask for object #…` | 确认选中单个 Mask 或带来源身份的参考框，模型为 Segment Anything |
| Interact 无法点击 | 解锁并显示目标；确认当前 Job 可编辑、模型已加载 |
| 切换模型后结果异常 | 按 [SAM 配置说明](../serverless/pytorch/facebookresearch/sam/README.md) 检查 `cvat.json`，重启 SAM 后刷新网页 |

其他序列重复第 3～8 节即可；标签继续沿用同一个 Project。

## 10. 来源数据的存储边界

Task 和 Shape 的来源信息统一使用 `ann_sources`，包含格式标识与载荷。例如，Shape 的来源记录为：

```json
{
  "format": "YTVIS 1.0",
  "data": {"video_id": 9, "instance_id": 55, "ref_bbox": [1, 2, 15, 16]}
}
```

参考框的内部名称是 `ref_bbox`；YTVIS 文件仍按标准使用 `bboxes`，
原数据的 `source_bboxes` 等来源字段也保持原名。

通用模型、标注读写和备份保存及传递来源载荷；格式适配器负责解释具体格式。
前端通过来源适配函数解析只读身份，用于显示和稳定配色，画布不判断 YTVIS 类型。
字段校验、参考框导出和原始身份重建由后端格式适配器负责。Shape 更新省略 `ann_sources`
时保留原关联，显式传入 `null` 时解除关联；删除 Shape 会删除其关联记录。
普通标注删除保留 Task 来源基线，因此删除全部 Mask 后仍可导出原始轨迹与 GT bbox。

迁移 `0111_ann_sources` 会转换旧数据库的专用记录，备份导入也兼容旧字段。
前端应与后端一起更新，以便在对象序列化时保留通用来源载荷。
