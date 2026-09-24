# ==========================================
#  `Project_Name` Project Makefile
# ==========================================

# 基本変数
NAME		:= Project_Name
UV			:= uv
PYTHON		:= python3
SRC_DIR		:= src
TEST_DIR	:= tests

# 追加変数(あれば)

# Mandatory requirements
# install, run, debug, clean, lint, lint-strict
.PHONY: all install run debug clean fclean lint lint-strict test lint-test uv-install re

all: install

# ---------------------
#  Environment Setup  |
# ---------------------
install: ## 仮想環境を作成し、依存関係をインストールする
	@echo "Creating virtual environment..."
	@echo "Installing dependencies..."
	@$(UV) sync
	@echo "Setup complete! Run 'make run' to start."

# -------------
#  Execution  |
# -------------
run: ## メインプログラムを実行
	@echo "Running $(NAME)..."
	@$(UV) run python3 -m $(SRC_DIR)

debug:
debug: ## pdbデバッガを使って実行
	@echo "Debugging $(NAME)..."
	@$(UV) run $(PYTHON) pdb -m $(SRC_DIR)

# -----------
#  Cleanup  |
# -----------
clean: ## 一時ファイルやキャッシュを削除
	@echo "Cleaning up..."
	@rm -rf __pycache__
	@rm -rf .mypy_cache
	@rm -rf .ruff_cache
	@rm -rf .pytest_cache
	@find . -type d -name "*.pyc" -exec rm -rf {} +
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@rm -rf dist
	@rm -rf build
	@rm -rf *.egg-info
	@echo "Clean complete."

fclean: clean ## cleanに加えて仮想環境も削除
	@echo "Full Cleaning up..."
	@rm -rf .venv
	@echo "Full Clean complete."

# -------------------
#  Quality Control  |
# -------------------
lint: ## Flake8 / Mypy / ruffによる静的解析を実行
	@echo "Running Linter (Standard)..."
	-@$(UV) run flake8 $(SRC_DIR)
	-@$(UV) run mypy $(SRC_DIR) 
	-@$(UV) run ruff check $(SRC_DIR)
# 	-@$(UV) run ty check $(SRC_DIR)
	@echo "Linting complete."

lint-strict: ## より厳しいMypyチェックを実行
	@echo "Running Linter (Strict)..."
	-@$(UV) run flake8 $(SRC_DIR)
	-@$(UV) run mypy --strict $(SRC_DIR)
	-@$(UV) run ruff check $(SRC_DIR)
# 	-@$(UV) run ty check $(SRC_DIR)
	@echo "Strict Linting complete."

# -----------
#  Testing  |
# -----------
test: ## pytestを実行
	@echo "Running Tests..."
	@$(UV) run pytest $(TEST_DIR)
	@echo "Testing complete."

lint-test: ## Flake8 / Mypy / ruffによる静的解析をテストディレクトリに対して実行
	@echo "Running Linter on Tests..."
	-@$(UV) run flake8 $(TEST_DIR)
	-@$(UV) run mypy $(TEST_DIR)
	-@$(UV) run ruff check $(TEST_DIR)
# 	-@$(UV) run ty check $(SRC_DIR)
	@echo "Linting Tests complete."

# -----------------------
#  Additional Commands  |
# -----------------------

uv-install: ## uvをインストールする
	@echo "Installing uv..."
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "uv installation complete."

re: fclean all ## すべてのファイルを削除して再度セットアップ
	@echo "Reinstalling $(NAME)..."