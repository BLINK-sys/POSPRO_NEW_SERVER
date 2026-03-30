"""
Safe formula evaluation engine using Python AST.
Only allows: numbers, arithmetic (+, -, *, /, **), comparisons,
and whitelisted functions (max, min, round, abs, ceil, floor).
No eval() or exec() — all expressions are parsed and walked safely.
"""

import ast
import math
import re
from typing import Dict, Optional, Tuple, List


ALLOWED_FUNCTIONS = {
    'max': max,
    'min': min,
    'round': round,
    'abs': abs,
    'ceil': math.ceil,
    'floor': math.floor,
}

BUILTIN_VARIABLE_NAMES = {
    'себестоимость',
    'курс_валюты',
    'длина',
    'ширина',
    'высота',
    'вес',
    # Габариты: произведение ДxШxВ с fallback (упаковка → без упаковки), 0 если оба пусты
    'габариты',
}

# Mapping from formula variable names to characteristic search patterns
CHARACTERISTIC_MAPPING = {
    'длина': ['длина'],
    'ширина': ['ширина'],
    'высота': ['высота'],
    'вес': ['вес', 'масса'],
}

# Characteristics that contain combined dimensions like "340х465х425"
DIMENSION_CHARACTERISTICS = {
    'размер_в_упаковке': ['размер в упаковке'],
    'размер_без_упаковки': ['размер без упаковки'],
}


class FormulaError(Exception):
    pass


class SafeEvaluator(ast.NodeVisitor):
    """Walks AST and evaluates only safe nodes."""

    def __init__(self, variables: Dict[str, float]):
        self.variables = variables

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise FormulaError(f"Недопустимое значение: {node.value}")

    def visit_Num(self, node):
        # Python 3.7 compatibility
        return float(node.n)

    def visit_Name(self, node):
        name = node.id
        if name in self.variables:
            return self.variables[name]
        raise FormulaError(f"Неизвестная переменная: '{name}'")

    def visit_UnaryOp(self, node):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise FormulaError(f"Недопустимая операция")

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise FormulaError("Деление на ноль")
            return left / right
        if isinstance(node.op, ast.Pow):
            return left ** right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise FormulaError("Деление на ноль")
            return left // right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise FormulaError("Деление на ноль")
            return left % right

        raise FormulaError(f"Недопустимая операция")

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name):
            raise FormulaError("Допустимы только простые вызовы функций")

        func_name = node.func.id
        if func_name not in ALLOWED_FUNCTIONS:
            raise FormulaError(
                f"Недопустимая функция: '{func_name}'. "
                f"Допустимые: {', '.join(ALLOWED_FUNCTIONS.keys())}"
            )

        args = [self.visit(arg) for arg in node.args]
        return ALLOWED_FUNCTIONS[func_name](*args)

    def visit_IfExp(self, node):
        # Support ternary: a if condition else b
        test = self.visit(node.test)
        if test:
            return self.visit(node.body)
        return self.visit(node.orelse)

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if isinstance(op, ast.Gt):
                result = left > right
            elif isinstance(op, ast.Lt):
                result = left < right
            elif isinstance(op, ast.GtE):
                result = left >= right
            elif isinstance(op, ast.LtE):
                result = left <= right
            elif isinstance(op, ast.Eq):
                result = left == right
            elif isinstance(op, ast.NotEq):
                result = left != right
            else:
                raise FormulaError("Недопустимое сравнение")
            if not result:
                return 0.0
            left = right
        return 1.0

    def visit_BoolOp(self, node):
        if isinstance(node.op, ast.And):
            result = all(self.visit(v) for v in node.values)
        elif isinstance(node.op, ast.Or):
            result = any(self.visit(v) for v in node.values)
        else:
            raise FormulaError("Недопустимая логическая операция")
        return 1.0 if result else 0.0

    def generic_visit(self, node):
        raise FormulaError(
            f"Недопустимая конструкция в формуле: {type(node).__name__}"
        )


def _normalize_formula(formula_text: str) -> str:
    """Replace comma decimal separators with dots, handle Russian chars."""
    # Replace , with . only when it looks like a decimal (e.g., 1,5 -> 1.5)
    result = re.sub(r'(\d),(\d)', r'\1.\2', formula_text)
    return result.strip()


def validate_formula(formula_text: str, available_vars: set) -> Optional[str]:
    """
    Validate a formula string.
    Returns None if valid, or error message string.
    """
    if not formula_text or not formula_text.strip():
        return "Формула не может быть пустой"

    formula_text = _normalize_formula(formula_text)

    try:
        tree = ast.parse(formula_text, mode='eval')
    except SyntaxError as e:
        return f"Синтаксическая ошибка: {e.msg}"

    # Check all variable names are known
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name = node.id
            if name not in available_vars and name not in ALLOWED_FUNCTIONS:
                return f"Неизвестная переменная: '{name}'"

    # Try evaluating with dummy values
    dummy_vars = {var: 1.0 for var in available_vars}
    try:
        evaluator = SafeEvaluator(dummy_vars)
        evaluator.visit(tree)
    except FormulaError as e:
        return str(e)
    except Exception as e:
        return f"Ошибка: {str(e)}"

    return None


def evaluate_formula(formula_text: str, variables: Dict[str, float]) -> float:
    """
    Evaluate a formula with given variables.
    Returns the calculated result.
    Raises FormulaError on any issue.
    """
    formula_text = _normalize_formula(formula_text)

    try:
        tree = ast.parse(formula_text, mode='eval')
    except SyntaxError as e:
        raise FormulaError(f"Синтаксическая ошибка: {e.msg}")

    evaluator = SafeEvaluator(variables)
    result = evaluator.visit(tree)

    if not isinstance(result, (int, float)):
        raise FormulaError("Формула должна возвращать число")

    if math.isnan(result) or math.isinf(result):
        raise FormulaError("Результат формулы: бесконечность или NaN")

    return float(result)


def calculate_product_price(
    cost_price: float,
    currency_rate: float,
    product_characteristics: Dict[str, float],
    warehouse_variables: List[dict],
    final_formula: str
) -> Tuple[float, Dict[str, float]]:
    """
    Calculate product price through warehouse formula chain.

    Args:
        cost_price: Product cost in warehouse currency
        currency_rate: Currency rate to tenge
        product_characteristics: Dict of characteristic values (длина, ширина, etc.)
        warehouse_variables: List of {name, formula} dicts, ordered by sort_order
        final_formula: The final price formula string

    Returns:
        Tuple of (calculated_price, all_variables_dict)
    """
    # Step 1: Build initial variables
    variables = {
        'себестоимость': cost_price,
        'курс_валюты': currency_rate,
    }

    # Add product characteristics
    for key in CHARACTERISTIC_MAPPING:
        variables[key] = product_characteristics.get(key, 0.0)

    # Габариты: ДxШxВ (произведение) с fallback упаковка → без упаковки → 0
    pack_dims = [
        product_characteristics.get(f'размер_в_упаковке_{s}', 0.0)
        for s in ['длина', 'ширина', 'высота']
    ]
    nopack_dims = [
        product_characteristics.get(f'размер_без_упаковки_{s}', 0.0)
        for s in ['длина', 'ширина', 'высота']
    ]

    if all(d > 0 for d in pack_dims):
        variables['габариты'] = pack_dims[0] * pack_dims[1] * pack_dims[2]
    elif all(d > 0 for d in nopack_dims):
        variables['габариты'] = nopack_dims[0] * nopack_dims[1] * nopack_dims[2]
    else:
        variables['габариты'] = 0.0

    # Step 2: Evaluate warehouse variables in order
    for var in warehouse_variables:
        var_name = var['name']
        var_formula = var['formula']
        try:
            value = evaluate_formula(var_formula, variables)
            variables[var_name] = value
        except FormulaError as e:
            raise FormulaError(
                f"Ошибка в переменной '{var_name}': {str(e)}"
            )

    # Step 3: Evaluate final formula
    try:
        price = evaluate_formula(final_formula, variables)
    except FormulaError as e:
        raise FormulaError(f"Ошибка в итоговой формуле: {str(e)}")

    return price, variables


def bulk_extract_product_characteristics(product_ids: list) -> Dict[int, Dict[str, float]]:
    """
    Extract characteristics for multiple products in bulk (2 queries total).
    Returns {product_id: {char_name: value, ...}, ...}
    """
    from models.characteristic import ProductCharacteristic
    from models.characteristics_list import CharacteristicsList

    if not product_ids:
        return {}

    # Fetch ALL characteristics for all products in one query
    all_chars = ProductCharacteristic.query.filter(
        ProductCharacteristic.product_id.in_(product_ids)
    ).all()

    # Collect all char_ids for CharacteristicsList lookup
    all_char_ids = set()
    for c in all_chars:
        try:
            all_char_ids.add(int(c.key))
        except (ValueError, TypeError):
            pass

    # Fetch all CharacteristicsList entries in one query
    char_list_map = {}
    if all_char_ids:
        char_list = CharacteristicsList.query.filter(
            CharacteristicsList.id.in_(list(all_char_ids))
        ).all()
        char_list_map = {ch.id: ch for ch in char_list}

    # Group characteristics by product_id
    product_chars_raw: Dict[int, list] = {}
    for c in all_chars:
        product_chars_raw.setdefault(c.product_id, []).append(c)

    # Process each product
    result: Dict[int, Dict[str, float]] = {}
    for pid in product_ids:
        chars = product_chars_raw.get(pid, [])
        product_result: Dict[str, float] = {}

        for c in chars:
            try:
                char_id = int(c.key)
            except (ValueError, TypeError):
                continue

            char_info = char_list_map.get(char_id)
            if not char_info:
                continue

            char_name = char_info.characteristic_key.lower().strip()

            for var_name, patterns in CHARACTERISTIC_MAPPING.items():
                for pattern in patterns:
                    if pattern in char_name:
                        numeric_value = _extract_number(c.value)
                        if numeric_value is not None:
                            product_result[var_name] = numeric_value
                        break

            for var_prefix, patterns in DIMENSION_CHARACTERISTICS.items():
                for pattern in patterns:
                    if pattern in char_name:
                        dims = _parse_dimensions(c.value)
                        if dims:
                            product_result[f'{var_prefix}_длина'] = dims[0]
                            product_result[f'{var_prefix}_ширина'] = dims[1]
                            product_result[f'{var_prefix}_высота'] = dims[2]
                        break

        result[pid] = product_result

    return result


def extract_product_characteristics(product_id: int) -> Dict[str, float]:
    """
    Extract dimension/weight characteristics from a product.
    Returns dict like:
      {'длина': 40.0, 'ширина': 30.0, 'высота': 25.0, 'вес': 8.0,
       'размер_в_упаковке_длина': 355, 'размер_в_упаковке_ширина': 465, ...}
    """
    from models.characteristic import ProductCharacteristic
    from models.characteristics_list import CharacteristicsList

    characteristics = ProductCharacteristic.query.filter_by(product_id=product_id).all()

    # Build map of characteristic_id -> CharacteristicsList
    char_ids = []
    for c in characteristics:
        try:
            char_ids.append(int(c.key))
        except (ValueError, TypeError):
            pass

    char_list_map = {}
    if char_ids:
        char_list = CharacteristicsList.query.filter(
            CharacteristicsList.id.in_(char_ids)
        ).all()
        char_list_map = {ch.id: ch for ch in char_list}

    result = {}

    for c in characteristics:
        try:
            char_id = int(c.key)
        except (ValueError, TypeError):
            continue

        char_info = char_list_map.get(char_id)
        if not char_info:
            continue

        char_name = char_info.characteristic_key.lower().strip()

        # Match single-value characteristics (длина, ширина, высота, вес)
        for var_name, patterns in CHARACTERISTIC_MAPPING.items():
            for pattern in patterns:
                if pattern in char_name:
                    numeric_value = _extract_number(c.value)
                    if numeric_value is not None:
                        result[var_name] = numeric_value
                    break

        # Match combined dimension characteristics (340х465х425)
        for var_prefix, patterns in DIMENSION_CHARACTERISTICS.items():
            for pattern in patterns:
                if pattern in char_name:
                    dims = _parse_dimensions(c.value)
                    if dims:
                        result[f'{var_prefix}_длина'] = dims[0]
                        result[f'{var_prefix}_ширина'] = dims[1]
                        result[f'{var_prefix}_высота'] = dims[2]
                    break

    return result


def _parse_dimensions(value_str: str) -> Optional[Tuple[float, float, float]]:
    """
    Parse combined dimensions like '340х465х425' or '340x465x425' or '340*465*425'.
    Returns (длина, ширина, высота) tuple or None.
    """
    if not value_str:
        return None

    # Replace comma decimal separators
    cleaned = value_str.replace(',', '.')

    # Split by various separators: х, x, X, Х, *, ×
    parts = re.split(r'[хХxX×*]', cleaned)

    if len(parts) < 3:
        return None

    try:
        nums = []
        for part in parts[:3]:
            # Extract number from each part
            match = re.search(r'[\d]+\.?[\d]*', part.strip())
            if match:
                nums.append(float(match.group()))
            else:
                return None

        if len(nums) == 3:
            return (nums[0], nums[1], nums[2])
    except (ValueError, IndexError):
        return None

    return None


def _extract_number(value_str: str) -> Optional[float]:
    """Extract first numeric value from a string like '150 мм' or '8,5 кг'."""
    if not value_str:
        return None

    # Replace comma with dot for decimal
    cleaned = value_str.replace(',', '.')

    # Find first number (including decimals)
    match = re.search(r'[\d]+\.?[\d]*', cleaned)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None
