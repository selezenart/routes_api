from trains.models import Train


def dfs_paths(graph, start, goal):
    """
    Function for searching of any kind of route from one city to another.
    Possibility of visiting one city more than one time is not included.
    """
    stack = [(start, [start])]
    while stack:
        (vertex, path) = stack.pop()
        if vertex in graph.keys():
            for next_ in graph[vertex] - set(path):
                if next_ == goal:
                    yield path + [next_]
                else:
                    stack.append((next_, path + [next_]))


def get_graph(qs):
    graph = {}
    for q in qs:
        graph.setdefault(q.departs_from_id, set())
        graph[q.departs_from_id].add(q.arrives_to_id)
    return graph


def get_routes(request, form) -> dict:
    context = {'form': form}
    qs = Train.objects.all().select_related('departs_from', 'arrives_to')
    data = form.cleaned_data
    start = data['departs_from']
    end = data['arrives_to']
    cities = data['cities']
    route_time = data['travel_duration']
    graph = get_graph(qs)
    all_routes = list(dfs_paths(graph, start.id, end.id))
    if not len(all_routes):
        raise ValueError("No routes, that can satisfy given requirements")
    if cities:
        cities_ids = [city.id for city in cities]
        satisfying_routes = []
        for route in all_routes:
            if all(city_id in route for city_id in cities_ids):
                satisfying_routes.append(route)
        if not satisfying_routes:
            raise ValueError("Route through these cities is impossible")
    else:
        satisfying_routes = all_routes.copy()
    routes = []
    all_trains = {}
    for q in qs:
        all_trains.setdefault((q.departs_from_id, q.arrives_to_id), [])
        all_trains[(q.departs_from_id, q.arrives_to_id)].append(q)
    for route in satisfying_routes:
        total_time = 0
        tmp = {'trains': []}
        for i in range(len(route) - 1):
            city_connection = all_trains[(route[i], route[i + 1])]
            train = city_connection[0]
            total_time += train.travel_time
            tmp['trains'].append(train)
        tmp['total_time'] = total_time
        if total_time <= route_time:
            routes.append(tmp)
    if not routes:
        raise ValueError("Minimal time for route is more than given")
    if len(routes) == 1:
        sorted_routes = routes
    else:
        sorted_routes = sorted(routes, key=lambda r: r['total_time'])
    context['routes'] = sorted_routes
    context['cities'] = {'startpoint': start.name, 'endpoint': end.name}
    return context
