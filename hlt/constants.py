"""
The constants representing the game variation being played.
They come from game engine and changing them has no effect.
They are strictly informational.
"""

SHIP_COST = 0
DROPOFF_COST = 0
MAX_HALITE = 0
MAX_TURNS = 0

EXTRACT_RATIO = 0
EXTRACT_MULTIPLIER = 0
MOVE_COST_RATIO = 0

INSPIRATION_ENABLED = True
INSPIRATION_RADIUS = 0
INSPIRATION_SHIP_COUNT = 0

INSPIRED_EXTRACT_RATIO = 0
INSPIRED_EXTRACT_MULTIPLIER = 0
INSPIRED_BONUS_MULTIPLIER = 0
INSPIRED_MOVE_COST_RATIO = 0

CAPTURE_ENABLED = True
CAPTURE_RADIUS = 0
CAPTURE_SHIP_ADVANTAGE = 0

WIDTH = 0
HEIGHT = 0

NUM_PLAYERS = 0
NUM_OPPONENTS = 0

CARDINAL_DIRECTIONS = [(1, 0), (0, 1), (-1, 0), (0, -1)]
ALL_DIRECTIONS = [(1, 0), (0, 1), (-1, 0), (0, -1), (0, 0)]


def load_constants(constants):
    """
    Load constants from JSON given by the game engine.
    """
    global SHIP_COST, DROPOFF_COST, MAX_HALITE, MAX_TURNS
    global EXTRACT_RATIO, EXTRACT_MULTIPLIER, MOVE_COST_RATIO
    global INSPIRATION_ENABLED, INSPIRATION_RADIUS, INSPIRATION_SHIP_COUNT
    global INSPIRED_EXTRACT_RATIO, INSPIRED_EXTRACT_MULTIPLIER, INSPIRED_BONUS_MULTIPLIER, INSPIRED_MOVE_COST_RATIO
    global CAPTURE_ENABLED, CAPTURE_RADIUS, CAPTURE_SHIP_ADVANTAGE

    """The cost to build a single ship."""
    SHIP_COST = constants['NEW_ENTITY_ENERGY_COST']

    """The cost to build a dropoff."""
    DROPOFF_COST = constants['DROPOFF_COST']

    """The maximum amount of halite a ship can carry."""
    MAX_HALITE = constants['MAX_ENERGY']

    """
    The maximum number of turns a game can last. This reflects the fact
    that smaller maps play for fewer turns.
    """
    MAX_TURNS = constants['MAX_TURNS']

    """1/EXTRACT_RATIO halite (truncated) is collected from a square per turn."""
    EXTRACT_RATIO = constants['EXTRACT_RATIO']
    EXTRACT_MULTIPLIER = 1 / EXTRACT_RATIO

    """1/MOVE_COST_RATIO halite (truncated) is needed to move off a cell."""
    MOVE_COST_RATIO = constants['MOVE_COST_RATIO']

    """Whether inspiration is enabled."""
    INSPIRATION_ENABLED = constants['INSPIRATION_ENABLED']

    """
    A ship is inspired if at least INSPIRATION_SHIP_COUNT opponent
    ships are within this Manhattan distance.
    """
    INSPIRATION_RADIUS = constants['INSPIRATION_RADIUS']

    """
    A ship is inspired if at least this many opponent ships are within
    INSPIRATION_RADIUS distance.
    """
    INSPIRATION_SHIP_COUNT = constants['INSPIRATION_SHIP_COUNT']

    """An inspired ship mines 1/X halite from a cell per turn instead."""
    INSPIRED_EXTRACT_RATIO = constants['INSPIRED_EXTRACT_RATIO']
    INSPIRED_EXTRACT_MULTIPLIER = 1 / INSPIRED_EXTRACT_RATIO

    """An inspired ship that removes Y halite from a cell collects X*Y additional halite."""
    INSPIRED_BONUS_MULTIPLIER = constants['INSPIRED_BONUS_MULTIPLIER']

    """An inspired ship instead spends 1/X% halite to move."""
    INSPIRED_MOVE_COST_RATIO = constants['INSPIRED_MOVE_COST_RATIO']

    """Whether capture is enabled."""
    CAPTURE_ENABLED = constants['CAPTURE_ENABLED']

    """
    A ship is captured if an opponent has this many more ships than
    you within CAPTURE_RADIUS distance.
    """
    CAPTURE_RADIUS = constants['CAPTURE_RADIUS']

    """
    A ship is captured if an opponent has CAPTURE_SHIP_ADVANTAGE more
    ships than you within this distance.
    """
    CAPTURE_SHIP_ADVANTAGE = constants['SHIPS_ABOVE_FOR_CAPTURE']


def set_dimensions(width, height):
    global WIDTH, HEIGHT
    WIDTH = width
    HEIGHT = height


def set_num_opponents(num_opponents):
    global NUM_PLAYERS, NUM_OPPONENTS
    NUM_PLAYERS = num_opponents + 1
    NUM_OPPONENTS = num_opponents
