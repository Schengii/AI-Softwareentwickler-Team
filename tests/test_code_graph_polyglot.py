"""
tests/test_code_graph_polyglot.py – Tests für polyglotte Code-Knowledge-Graph-Indexierung (TS, Go, Rust, Python)
"""


from core.code_graph import CodebaseGraph


def test_codebase_graph_polyglot(tmp_path):
    # 1. Python file
    py_file = tmp_path / "service.py"
    py_file.write_text("""
class UserService:
    def get_user(self, user_id):
        return {"id": user_id}
""", encoding="utf-8")

    # 2. TypeScript file
    ts_file = tmp_path / "types.ts"
    ts_file.write_text("""
export interface UserDTO {
    id: string;
    name: string;
}

export async function fetchUser(userId: string) {
    return { id: userId, name: "Test" };
}
""", encoding="utf-8")

    # 3. Go file
    go_file = tmp_path / "handler.go"
    go_file.write_text("""
package main

import "fmt"

type Handler struct {
    port int
}

func (h *Handler) ServeHTTP(w string) {
    fmt.Println(w)
}

func NewHandler(port int) *Handler {
    return &Handler{port: port}
}
""", encoding="utf-8")

    # 4. Rust file
    rs_file = tmp_path / "lib.rs"
    rs_file.write_text("""
use std::sync::Arc;

pub struct Config {
    pub timeout: u64,
}

pub trait Runner {
    fn run(&self);
}

pub fn init_config() -> Config {
    Config { timeout: 30 }
}
""", encoding="utf-8")

    graph = CodebaseGraph(tmp_path)
    assert graph.indexed_files_count == 4

    # Check Python
    py_defs = graph.find_definition("UserService")
    assert len(py_defs) == 1
    assert py_defs[0].kind == "class"

    # Check TS
    ts_defs = graph.find_definition("UserDTO")
    assert len(ts_defs) == 1
    assert ts_defs[0].kind == "interface"

    ts_func = graph.find_definition("fetchUser")
    assert len(ts_func) == 1
    assert ts_func[0].kind == "function"

    # Check Go
    go_struct = graph.find_definition("Handler")
    assert len(go_struct) == 1
    assert go_struct[0].kind == "struct"

    go_method = graph.find_definition("Handler.ServeHTTP")
    assert len(go_method) == 1
    assert go_method[0].kind == "method"

    # Check Rust
    rs_struct = graph.find_definition("Config")
    assert len(rs_struct) == 1
    assert rs_struct[0].kind == "struct"

    rs_trait = graph.find_definition("Runner")
    assert len(rs_trait) == 1
    assert rs_trait[0].kind == "trait"
