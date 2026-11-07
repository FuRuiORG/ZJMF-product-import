# ZJMF-product-import

批量导入智简魔方(ZJMF)上游产品的命令行脚本，支持自动创建分组与折扣分组。

## 环境

- Python 3.6+
- `requests`，可选`pypinyin`用于拼音首字母

## 运行

```bash
pip install requests
pip install pypinyin
python product_import.py
```

## 使用

按提示输入后台地址、后台路径、账号密码，选择上游与导入模式，再选择分组并确认。

一级分组命名为「上游拼音首字母-分组名」，例如`MD-香港`。导入完成后按折扣创建分组（如`60`、`70`）并归入产品。每批最多导入50个产品。

## 配置

可选择保存到`config.json`：

```json
{
  "base_url": "https://xxx.com",
  "admin_path": "admin2024",
  "username": "admin"
}
```

## 说明

- 默认忽略SSL证书校验
- 默认按原价100%导入
- 目前建议只使用一级分组导入
