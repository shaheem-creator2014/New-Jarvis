"""Validated tools: each returns concise spoken output and a structured result."""
from .windows import approved_application, approved_website, launch_application, launch_website


def result(spoken, **data):
    return {'spoken': spoken, **data}


def search_brain(index, query):
    if not isinstance(query, str) or not query.strip() or len(query) > 300:
        raise ValueError('Search must contain 1–300 characters')
    rows = index.search(query.strip())
    return result(f'{len(rows)} matching documents, Shaheem.' if rows else 'No matching indexed documents, Shaheem.',
                  tool='search_brain', ok=True, results=rows)


def validate_action(action, argument):
    if action == 'open_website':
        return approved_website(argument)
    if action == 'windows_control':
        return approved_application(argument)
    raise ValueError('This action cannot be confirmed')


def execute_action(action, argument):
    argument = validate_action(action, argument)
    outcome = launch_website(argument) if action == 'open_website' else launch_application(argument)
    return {'tool': action, **outcome}


def plan_day(tasks):
    """Rank only owner-supplied tasks; never infer a date, task, or commitment."""
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 30:
        raise ValueError('Supply 1–30 actual tasks')
    items = []
    for position, task in enumerate(tasks):
        if not isinstance(task, dict) or set(task) != {'text', 'category', 'urgent'}:
            raise ValueError('Each task needs text, category and urgent')
        text, category, urgent = task['text'], task['category'], task['urgent']
        categories = {'school': 0, 'commitment': 1, 'robotics': 2, 'website': 3, 'content': 4, 'other': 5}
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 300 or not isinstance(category, str) or category not in categories or type(urgent) is not bool:
            raise ValueError('Invalid task text, category or urgency')
        items.append((not urgent, categories[category], position, {'text': text.strip(), 'category': category, 'urgent': urgent}))
    priorities = [item[3] for item in sorted(items)[:5]]
    return result(f'Your plan has {len(priorities)} priorities, Shaheem. Review it before acting.', tool='plan_day',
                  ok=True, priorities=priorities, method='Owner-marked urgency first, then school, commitments, robotics, websites and content. No deadlines inferred.')


def limited_command(text, index):
    """Explicit commands are deliberately separate from model interpretation."""
    command, _, argument = text.strip().partition(' ')
    if command == '/search':
        return search_brain(index, argument)
    if command == '/plan':
        return result('Enter your actual tasks and mark time-sensitive work, Shaheem.', tool='plan_day', ok=True, needs_tasks=True)
    if command in {'/app', '/open'}:
        action = 'windows_control' if command == '/app' else 'open_website'
        return {'action': action, 'argument': validate_action(action, argument.strip().lower())}
    if command == '/help':
        return result('Limited commands: /search words, /app vscode|calculator|notepad|explorer, /open github|youtube|vercel|lovable, /plan, /inbox, /calendar today|upcoming|query, /brief, /research query, /remember fact, /memory, /recall words. These are explicit commands, not AI reasoning.', ok=True, tool='help')
    raise ValueError('Unknown limited command. Use /help.')
