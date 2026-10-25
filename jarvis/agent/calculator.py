"""Bounded arithmetic only: no eval, names, calls, attributes or executable code."""
import ast
import re
from fractions import Fraction
from decimal import Decimal, localcontext


def calculate(text):
    expression = text.strip().lower()
    expression = re.sub(r'^(?:jarvis[, ]+)?(?:what is|what\'s|calculate|compute|solve)\s+', '', expression)
    expression = expression.rstrip(' ?=')
    for word, symbol in [('multiplied by', '*'), ('divided by', '/'), ('times', '*'), ('plus', '+'), ('minus', '-')]:
        expression = re.sub(r'\b' + word + r'\b', symbol, expression)
    expression = expression.replace('×', '*').replace('÷', '/').replace('−', '-').replace('^', '**')
    expression = re.sub(r'(?<=\d)\s*x\s*(?=\d)', '*', expression)
    if not expression or not re.fullmatch(r'[\d\s.+*/%()\-]+', expression) or not re.search(r'\d', expression):
        return None
    if len(expression) > 160:
        return _error('That arithmetic expression is too long.')
    try:
        tree = ast.parse(expression, mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError('Too many operations.')

        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = Fraction(ast.get_source_segment(expression, node))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp):
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add): value = left + right
                elif isinstance(node.op, ast.Sub): value = left - right
                elif isinstance(node.op, ast.Mult): value = left * right
                elif isinstance(node.op, ast.Div): value = left / right
                elif isinstance(node.op, ast.Mod): value = left % right
                elif isinstance(node.op, ast.Pow) and right.denominator == 1 and abs(right) <= 100:
                    value = left ** int(right)
                else: raise ValueError('Unsupported operator or exponent. Exponents must be integers from -100 to 100.')
            else:
                raise ValueError('Use only numbers, parentheses and arithmetic operators.')
            if value.numerator.bit_length() > 4096 or value.denominator.bit_length() > 4096:
                raise ValueError('The result is too large.')
            return value

        value = visit(tree.body)
        exact = value.denominator == 1
        if exact:
            display = format(value.numerator, ',')
        else:
            with localcontext() as context:
                context.prec = 16
                decimal = Decimal(value.numerator) / Decimal(value.denominator)
                display = format(decimal, ',f').rstrip('0').rstrip('.')
            exact = Fraction(decimal) == value
        return {'ok': True, 'tool': 'calculator', 'engine': 'Local calculator · not AI-generated',
                'spoken': f'{display}' + ('' if exact else ' (approximately)') + ', Shaheem.',
                'calculation': {'expression': expression, 'result': display, 'exact': exact}}
    except ZeroDivisionError:
        return _error('Division by zero is undefined.')
    except (ValueError, SyntaxError, OverflowError, RecursionError) as error:
        return _error(str(error) if isinstance(error, ValueError) else 'Check the arithmetic expression and parentheses.')


def _error(message):
    return {'ok': False, 'tool': 'calculator', 'engine': 'Local calculator · not AI-generated',
            'spoken': message + ' No AI estimate was substituted, Shaheem.'}
