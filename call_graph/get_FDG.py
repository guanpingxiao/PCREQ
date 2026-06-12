import requests
import json
import os
import ast, re
import time
import platform
from utils.util import is_version_compat

if (platform.system() == 'Windows'):
    slash = "\\"
else:
    slash = r"/"

library_path_prefix = ""
constraint_path_prefix = ""
version_path_prefix = ""
api_path_prefix = ""

def setup_path_1(library_path_prefix_pass, constraint_path_prefix_pass, version_path_prefix_pass, api_path_prefix_pass):
    global library_path_prefix, constraint_path_prefix, version_path_prefix, api_path_prefix
    library_path_prefix = library_path_prefix_pass
    constraint_path_prefix = constraint_path_prefix_pass
    version_path_prefix = version_path_prefix_pass
    api_path_prefix = api_path_prefix_pass

def split_and_take_first_part(elements):
    # 使用列表推导式处理每个元素
    #return [element.split(';')[0].strip() for element in elements]
    res =[]
    for element in elements:
        if ';' in element:
            res.append(element.split(';')[0])
        else:
            res.append(element)
    return res

def split_packname_and_cons(line):
    version_ops = [r'<', r'<=', r'!=', r'==', r'>=', r'>', r'~=', r'===']
    min_op_idx = None
    for op in version_ops:
        if line.find(op) != -1:
            if min_op_idx == None:
                min_op_idx = line.find(op)
            else:
                min_op_idx = min(min_op_idx, line.find(op))
    res = []
    if min_op_idx != None:
        res.append(line[:min_op_idx])
        res.append(line[min_op_idx:])
    else:
        res.append(line)
    for i in range(len(res)):
        res[i]=res[i].replace(" ","").split('[')[0].lower()
    return res

def remove_parentheses_from_end(elements):
    # 使用列表推导式处理每个元素
    return [element.rstrip('()') for element in elements]

def download_json(url, filename):
    # 发送 HTTP GET 请求，网络错误时重试3次
    for retry in range(3):
        try:
            response = requests.get(url, timeout=60)
            break
        except requests.RequestException:
            if retry == 2:
                print(f"Failed to retrieve data after 3 retries: {url}")
                return
            time.sleep(2 ** retry)
    else:
        return
    tmp_filename = filename + ".tmp"
    # 确认请求成功
    if response.status_code == 200:
        # 将 JSON 数据加载成 Python 对象
        data = response.json()
        # 原子写入: 先写临时文件, 再 rename
        with open(tmp_filename, 'w') as file:
            json.dump(data, file, indent=4)
        os.replace(tmp_filename, filename)
        print(f"Data has been saved to {filename}")
    elif response.status_code == 404:
        # write placeholder for truly missing packages to avoid repeated attempts
        print(f"Package not found: Status code {response.status_code}")
        with open(tmp_filename, 'w') as file:
            json.dump({"message": "Not Found"}, file)
        os.replace(tmp_filename, filename)
    else:
        print(f"Failed to retrieve data: Status code {response.status_code}")

def download_from_data(package, package_version):
    print(package)
    url = 'https://pypi.tuna.tsinghua.edu.cn/pypi/' + package  +'/json'
    #print(url)
    #package_versions = ["1.2.0"]
    #package_versions = fetch_package_versions(url)
    #time.sleep(2)
    #print(package_versions)
    url2 = 'https://pypi.org/pypi/' + package + '/' + package_version +'/json'
    path = constraint_path_prefix + package + '/' + package + package_version
    if not os.path.exists(path):
        os.makedirs(path)
    download_json(url2, path + '/' + package + '.json')

def remove_elements_with_extra(lst):
    # 使用列表推导式过滤掉包含'docs'或'tests'的元素
    #return [item for item in lst if 'extra' not in item]
    new_requires_dist = []
    for item in lst:
        if 'extra' in item and 'alldeps' in item:
            new_requires_dist.append(item)
        elif 'extra' not in item:
            new_requires_dist.append(item)
    return new_requires_dist

def _platform_mismatch(condition):
    """Return True if PEP 508 sys_platform marker is incompatible with current platform."""
    import sys
    if 'sys_platform' not in condition:
        return False
    is_linux = sys.platform.startswith('linux')
    is_mac = sys.platform == 'darwin'
    is_win = sys.platform == 'win32'
    if ('"linux"' in condition or "'linux'" in condition) and not is_linux:
        return True
    if ('"darwin"' in condition or "'darwin'" in condition) and not is_mac:
        return True
    if ('"win32"' in condition or "'win32'" in condition) and not is_win:
        return True
    return False


# TODO 目前是将所有对python_version有约束的都去掉，但是应该考虑是否符合约束
# KB-11: 追加 sys_platform 过滤，避免 Linux 上引入 win32-only 依赖（如 gevent→cffi）
def remove_incompat_python_version(requires_dist, python_version):
    new_requires_dist = []
    for item in requires_dist:
        if ';' in item:
            condition = item.split(';', 1)[1].strip()
            if _platform_mismatch(condition):
                continue
            if 'python_version' in condition:
                continue
        new_requires_dist.append(item)
    return new_requires_dist

def get_tree(filename):
    def get_tree_with_feature_version(filename, feature_version=None):
        """
        Get the entire AST for this file

        :param filename str:
        :rtype: ast
        """
        try:
            with open(filename) as f:
                raw = f.read()
        except ValueError:
            with open(filename, encoding='UTF-8', errors='ignore') as f:
                raw = f.read()
        if feature_version == None:
            tree = ast.parse(raw)
        else:
            tree = ast.parse(raw, feature_version=feature_version)
        return tree

    try:
        tree = get_tree_with_feature_version(filename, feature_version=(3, 8))
        return tree
    except:
        try:
            tree = get_tree_with_feature_version(filename)
            return tree
        except:
            try:
                tree = get_tree_with_feature_version(filename, feature_version=(3, 4))
                return tree
            except:
                return None

def find_setup_path(dir_path):
        """
        find setup.py path
        :param dir_path:
        :return: setpy.py path or None
        """
        setup_path = None
        for f in os.listdir(dir_path):
            full_f = os.path.join(dir_path, f)
            if full_f.endswith(r"\setup.py") or full_f.endswith(r"/setup.py"):
                setup_path = full_f
                break

        if setup_path == None:
            parent_dir_path = slash.join(dir_path.split(slash)[:-1])
            for f in os.listdir(parent_dir_path):
                full_f = os.path.join(parent_dir_path, f)
                if full_f.endswith(r"\setup.py") or full_f.endswith(r"/setup.py"):
                    setup_path = full_f
                    break

        return setup_path

def get_packname_and_cons_from_setup(librarypath):
    setupfilepath = find_setup_path(librarypath)

    try:
        r_node = get_tree(setupfilepath)
    except SyntaxError:
        return []
    
    if r_node == None:
        return []

    install_requires = None
    res = []
    for element in ast.walk(r_node):
        if type(element) == ast.Call and ((type(element.func) == ast.Name and element.func.id == "setup") or
                                          ((type(element.func) == ast.Attribute and type(element.func.value)==ast.Name and element.func.value.id == "setuptools" and element.func.attr=="setup"))):
            for keyword in element.keywords:
                if keyword.arg in ["install_requires","setup_requires"]:
                    install_requires = keyword.value
                    break

            if install_requires == None:
                pass

            break

    if install_requires == None:
        return []

    if type(install_requires) not in [ast.Name, ast.List]:
        return []

    assert type(install_requires) in [ast.Name, ast.List]
    if type(install_requires) == ast.Name:
        to_search_str = install_requires.id
        install_requires = None
        for element in ast.walk(r_node):
            if type(element) == ast.Assign:
                for target in element.targets:
                    if hasattr(target, "id") and target.id == to_search_str and hasattr(element, "value") and type(element.value) == ast.List:
                        install_requires = element.value

    if install_requires == None:
        return []

    assert type(install_requires) == ast.List
    for single_req in install_requires.elts:
        if type(single_req) == ast.BinOp:
            continue

        assert type(single_req) in [ast.Str, ast.Constant]
        if type(single_req)==ast.Str:
            res.append(split_packname_and_cons(single_req.s))
        else:
            res.append(split_packname_and_cons(single_req.value))



    return res

def get_library_constraint_from_metadata(pkg, version, python_version):
    res = {}
    requires_dist = None

    # Priority 1: local .dist-info/METADATA (most reliable)
    metadata_path = f"{library_path_prefix}{pkg}/{pkg}{version}/{pkg}-{version}.dist-info/METADATA"
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as file:
                metadata = file.read()
            requires_dist_pattern = r"Requires-Dist: (.+?)(?=\n|$)"
            requires_dist = re.findall(requires_dist_pattern, metadata)
        except Exception:
            pass

    # Priority 2: setup.py (source distribution)
    if requires_dist is None:
        library_path = f"{library_path_prefix}{pkg}/{pkg}{version}/{pkg}"
        if os.path.exists(library_path):
            s = get_packname_and_cons_from_setup(library_path)
            for i in s:
                if len(i) == 2:
                    res[i[0]] = i[1].replace("-", ".")
                else:
                    res[i[0]] = None
            return res

    # Priority 3: PyPI JSON (fallback, may have data loss)
    if requires_dist is None:
        json_path = constraint_path_prefix + pkg + '/' + pkg + version + '/' + pkg + '.json'
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as file:
                    data = json.load(file)
            except Exception:
                print(f"No {pkg}: {version} version constraint")
                download_from_data(pkg, version)
            try:
                requires_dist = data.get('info', {}).get('requires_dist')
            except Exception:
                requires_dist = None

    if requires_dist is not None:
        requires_dist = remove_elements_with_extra(requires_dist)
        requires_dist = remove_incompat_python_version(requires_dist, python_version)
        new_requires_dist = split_and_take_first_part(requires_dist)
        for i in range(len(requires_dist)):
            tmp = requires_dist[i]
            tmp = tmp.split(';')[0]
            new_requires_dist[i] = split_packname_and_cons(tmp)
            tmp1 = new_requires_dist[i]
            new_requires_dist[i] = remove_parentheses_from_end(tmp1)
    else:
        new_requires_dist = None

    if new_requires_dist is not None:
        for i in new_requires_dist:
            try:
                res[i[0]] = i[1].replace("-", ".")
            except Exception:
                res[i[0]] = None
    return res 

def get_library_dependency_from_metadata(pkg, version, python_version):
    res = []

    library_constraint = get_library_constraint_from_metadata(pkg, version, python_version)
    for library in library_constraint:
        res.append(library)

    return res 


def get_FDG_from_requirements(proj_dependency, python_version):
    res = {}

    #proj_dependency = get_proj_dependency_from_requirements(file_path)
    for library in proj_dependency:
        res[library] = get_library_dependency_from_metadata(library, proj_dependency[library], python_version)
        #print(res[library])
        #pass
    res = {node.lower(): [neighbor.lower() for neighbor in neighbors] for node, neighbors in res.items()}
    return res

def reachable_nodes(graph, start_node):
    visited = set()
    #start_node = start_node.lower

    def dfs(node):
        if node not in visited:
            #print(node)
            visited.add(node)
            for neighbor in graph.get(node, []):
                dfs(neighbor)

    dfs(start_node)
    return visited

def build_undirected_graph(graph):
    undirected_graph = {}
    for node, neighbors in graph.items():
        if node not in undirected_graph:
            undirected_graph[node] = []
        for neighbor in neighbors:
            if neighbor not in undirected_graph:
                undirected_graph[neighbor] = []
            undirected_graph[node].append(neighbor)
            undirected_graph[neighbor].append(node)  # 添加反向边
    return undirected_graph

def get_sub_graph(graph, node):
    sub_graph = {}

    undirected_graph = build_undirected_graph(graph)
    #print(graph)
    visited = reachable_nodes(undirected_graph, node)
    for i in visited:
        try:
            sub_graph[i] = graph[i]
        except:
            continue
    return sub_graph
'''
if __name__ == '__main__':
    res = get_library_dependency_from_metadata('tensorflow', '2.6.2')
    print(res)
'''