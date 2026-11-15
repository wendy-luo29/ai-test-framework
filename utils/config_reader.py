import yaml
import os

def load_config(config_file_name):
    """
    读取 config 文件夹下的 YAML 配置文件
    例如：load_config("base_url.yaml")
    """
    # 获取项目根目录的路径
    base_path = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(base_path, "config", config_file_name)
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件 {config_path} 不存在！")
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)