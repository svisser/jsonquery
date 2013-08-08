import operator
import collections
import sqlalchemy

DEFAULT_QUERY_CONSTRAINTS = {
    'max_breadth': None,
    'max_depth': None,
    'max_elements': 64
}

NUMERIC_OPERATORS = {
    '<': operator.lt,
    '<=': operator.le,
    '!=': operator.ne,
    '==': operator.eq,
    '>=': operator.ge,
    '>': operator.gt,
}

STRING_OPERATORS = {
    'like': lambda col, value: getattr(col, 'like')(value),
    'ilike': lambda col, value: getattr(col, 'ilike')(value)
}

TYPE_OPERATORS = {
    sqlalchemy.types.String: STRING_OPERATORS,
    sqlalchemy.types.Integer: NUMERIC_OPERATORS
}

def jsonquery(session, model, json, **kwargs):
    '''
    Returns a query object built from the given json.
    Usage:
        query = jsonquery(session, model, json, query_constraints)
        rows = query.all()

    session:
        SQLAlchemy session to build query on

    model:
        SQLAlchemy model to perform queries on

    json:
        Logical Operators
            {
                operator: 'and',
                value: [
                    OBJ1,
                    OBJ2,
                    ...
                    OBJN
                ]
            }
        Columns: Numeric
            {
                column: 'age',
                operator: '>=',
                value: 18
            }
        Columns: Strings
            {
                column: 'name',
                operator: 'ilike',
                value: 'pat%'
            }

        Logical operators 'and' and 'or' take an array, while 'not' takes a single value.
        It is invalid to have a logical operator as the value of a subquery.

        Numeric operators are:
            <, <=, ==, !=, >=, >
        String operators are:
            like    case-sensitive match
            ilike   case-insensitive match

            String wildcard character is % (so "pat%" matches "patrick" and "patty")
            with default escape character '/'

    max_breadth (Optional):
        Maximum number of elements in a single and/or operator. Default is None.

    max_depth (Optional):
        Maximum nested depth of a constraint.  Default is None.

    max_elements (Optional):
        Maximum number of constraints and logical operators allowed in a query.  Default is 64.
    '''
    constraints = dict(DEFAULT_QUERY_CONSTRAINTS)
    constraints.update(kwargs)
    count = depth = 0
    criterion, total_elements = _build(json, count, depth, model, constraints)
    return session.query(model).filter(criterion)

def _build(node, count, depth, model, constraints):
    count += 1
    depth += 1
    value = node['value']
    _validate_query_constraints(value, count, depth, constraints)
    logical_operators = {
        'and': (_build_sql_sequence, sqlalchemy.and_),
        'or': (_build_sql_sequence, sqlalchemy.or_),
        'not': (_build_sql_unary, sqlalchemy.not_),
    }
    op = node['operator']
    if op in logical_operators:
        builder, func = logical_operators[op]
        return builder(node, count, depth, model, constraints, func)
    else:
        return _build_column(node, model), count

def _validate_query_constraints(value, count, depth, constraints):
        '''Raises if any query constraints are violated'''
        max_breadth = constraints['max_breadth']
        max_depth = constraints['max_depth']
        max_elements = constraints['max_elements']

        if max_depth and depth > max_depth:
            raise ValueError('Depth limit ({}) exceeded'.format(max_depth))

        element_breadth = 1
        if isinstance(value, collections.Sequence) and not isinstance(value, basestring):
            element_breadth = len(value)

        if max_breadth and element_breadth > max_breadth:
                raise ValueError('Breadth limit ({}) exceeded'.format(max_breadth))

        count += element_breadth
        if max_elements and count > max_elements:
            raise ValueError('Filter elements limit ({}) exceeded'.format(max_elements))

def _build_sql_sequence( node, count, depth, model, constraints, func):
    '''
    func is either sqlalchemy.and_ or sqlalchemy.or_
    Build each subquery in node['value'], then combine with func(*subqueries)
    '''
    subqueries = []
    for value in node['value']:
        subquery, count = _build(value, count, depth, model, constraints)
        subqueries.append(subquery)
    return func(*subqueries), count

def _build_sql_unary( node, count, depth, model, constraints, func):
    '''
    func is sqlalchemy.not_ (may support others)
    '''
    value = node['value']
    subquery, count = _build(value, count, depth, model, constraints)
    return func(subquery), count

def _build_column(node, model):
    # string => sqlalchemy.orm.attributes.InstrumentedAttribute
    column = node['column']
    column = getattr(model, column)
    ctype = type(column.type)

    op = node['operator']
    value = node['value']

    op_map = TYPE_OPERATORS[ctype]  # Get a set of operators for the type
    func = op_map[op]  # Get the function for the operator
    return func(column, value)
