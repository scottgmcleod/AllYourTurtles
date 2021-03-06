#!/usr/bin/env python3

import hlt
from hlt import constants
from copy import deepcopy
from datetime import datetime
import logging
from collections import defaultdict
import math
from math import ceil, floor
from statistics import mean
from heapq import nlargest
import gc

gc.disable()

GAME = hlt.Game()
MAP = GAME.game_map
ME = GAME.me
OTHER_PLAYERS = [GAME.players[oid] for oid in GAME.others]

TURNS_REMAINING = 0
ENDGAME = False

SHIPS = []
N = 0
OTHER_SHIPS = []
OPPONENT_NS = []
TOTAL_N = 0

DROPOFFS = set()
DROPOFF_RADIUS = 8 if constants.NUM_PLAYERS == 2 else 4
DROPOFF_COST_MULT = 5 if constants.NUM_PLAYERS == 2 else 3
OPPONENT_DROPOFFS = []
DROPOFF_BY_POS = {}  # the closest dropoff for each position
DROPOFF_DIST_BY_POS = {}  # the distance to the closest dropoff for each position

OPPONENTS_AROUND = {}  # the number of opponent ships around (within 4 distance) a position
ALLIES_AROUND = {}  # the number of ally ships around (within 4 distance) a position
INSPIRED_BY_POS = {}  # whether or not the position is inspired
EXTRACT_MULTIPLIER_BY_POS = {}  # the extraction multiplier for each position
BONUS_MULTIPLIER_BY_POS = {}  # the bonus multiplier for each position
DIFFICULTY = {}  # the difficulty of getting to a position

SIZE = constants.WIDTH * constants.HEIGHT
HALF_SIZE = SIZE // 2
TOTAL_HALITE = sum(MAP[p].halite_amount for p in MAP.positions)
HALITE_REMAINING = TOTAL_HALITE
PCT_REMAINING = HALITE_REMAINING / TOTAL_HALITE
PCT_COLLECTED = 1 - PCT_REMAINING
REMAINING_WEIGHT = constants.NUM_OPPONENTS + PCT_REMAINING
COLLECTED_WEIGHT = constants.NUM_OPPONENTS + PCT_COLLECTED

ROI = 0

MAX_ASSIGNMENTS = 100 * 100

PROB_OCCUPIED = {}


def main():
    commander = Commander()
    while True:
        commander.run_once()


class Commander:
    def __init__(self):
        GAME.ready("AllYourTurtles")
        self.opponent_model = OpponentModel()

    def run_once(self):
        GAME.update_frame()
        self.update_globals()
        # TOOD this should've been above update_globals
        # start_time = datetime.now()
        # log('Starting turn {}'.format(GAME.turn_number))
        queue = self.produce_commands()
        GAME.end_turn(queue)
        # log('Turn took {}'.format((datetime.now() - start_time).total_seconds()))

    def update_globals(self):
        """
        Updates all the global data that is used throughout the bot.
        :return:
        """
        global GAME, MAP, ME, OTHER_PLAYERS, TURNS_REMAINING, ENDGAME, SHIPS, N, OTHER_SHIPS, OPPONENT_NS, TOTAL_N
        global DROPOFFS, OPPONENT_DROPOFFS, DROPOFF_BY_POS, DROPOFF_DIST_BY_POS
        global OPPONENTS_AROUND, ALLIES_AROUND, INSPIRED_BY_POS, EXTRACT_MULTIPLIER_BY_POS, BONUS_MULTIPLIER_BY_POS
        global HALITE_REMAINING, PCT_REMAINING, PCT_COLLECTED, DIFFICULTY, REMAINING_WEIGHT, COLLECTED_WEIGHT
        global PROB_OCCUPIED, ROI

        # log('Updating data...')

        TURNS_REMAINING = constants.MAX_TURNS - GAME.turn_number
        SHIPS = ME.get_ships()
        N = len(SHIPS)
        OTHER_SHIPS = []
        OPPONENT_NS = []
        for other in OTHER_PLAYERS:
            OTHER_SHIPS.extend(other.get_ships())
            OPPONENT_NS.append(len(other.get_ships()))
        TOTAL_N = N + len(OTHER_SHIPS)
        # log('N={} ON={}'.format(N, OPPONENT_NS))

        self.opponent_model.update_all()
        prob_by_pos = self.opponent_model.prob_occupied()

        OPPONENTS_AROUND = defaultdict(int)
        ALLIES_AROUND = defaultdict(int)
        for ship in SHIPS:
            for p in pos_around(ship.pos, constants.INSPIRATION_RADIUS):
                ALLIES_AROUND[p] += 1
        for ship in OTHER_SHIPS:
            for p in pos_around(ship.pos, constants.INSPIRATION_RADIUS):
                OPPONENTS_AROUND[p] += 1

        DROPOFFS = set([ME.shipyard.pos] + [drp.pos for drp in ME.get_dropoffs()])

        OPPONENT_DROPOFFS = []
        for player in OTHER_PLAYERS:
            OPPONENT_DROPOFFS.append(player.shipyard.pos)
            for drp in player.get_dropoffs():
                OPPONENT_DROPOFFS.append(drp.pos)

        halite = 0
        for pos in MAP.positions:
            drp = min(DROPOFFS, key=lambda drp: MAP.dist(drp, pos))
            drp_dist = MAP.dist(pos, drp)
            inspired = OPPONENTS_AROUND[pos] >= constants.INSPIRATION_SHIP_COUNT
            extract = constants.INSPIRED_EXTRACT_MULTIPLIER if inspired else constants.EXTRACT_MULTIPLIER
            bonus = constants.INSPIRED_BONUS_MULTIPLIER if inspired else 0
            DROPOFF_BY_POS[pos] = drp
            DROPOFF_DIST_BY_POS[pos] = drp_dist
            INSPIRED_BY_POS[pos] = inspired
            EXTRACT_MULTIPLIER_BY_POS[pos] = extract
            BONUS_MULTIPLIER_BY_POS[pos] = bonus
            DIFFICULTY[pos] = 0
            halite += MAP[pos].halite_amount * (1 + bonus)
            PROB_OCCUPIED[pos] = prob_by_pos[pos]
        HALITE_REMAINING = halite
        PCT_REMAINING = halite / TOTAL_HALITE
        PCT_COLLECTED = 1 - PCT_REMAINING
        REMAINING_WEIGHT = constants.NUM_OPPONENTS + PCT_REMAINING
        COLLECTED_WEIGHT = constants.NUM_OPPONENTS + PCT_COLLECTED

        for drp in DROPOFFS:
            DIFFICULTY[drp] = OPPONENTS_AROUND[drp]

        SHIPS = sorted(SHIPS,
                       key=lambda ship: (DROPOFF_DIST_BY_POS[ship.pos], -ship.halite_amount, ship.id))

        if not ENDGAME:
            ENDGAME = any(DROPOFF_DIST_BY_POS[ship.pos] >= TURNS_REMAINING for ship in SHIPS) or PCT_REMAINING == 0

        ROI = IncomeEstimation.roi()

        # log('Updated data')

    def should_make_ship(self, goals):
        """
        Whether we should make a new ship or not. Tries to match the opponent number of ships if we are lower,
        otherwise only make one if the ROI is positive.
        :param goals:
        :return:
        """
        if ENDGAME:
            return False

        for i in range(N):
            if MAP.dist(SHIPS[i].pos, ME.shipyard.pos) == 1 and goals[i] == ME.shipyard.pos:
                return False

        my_produced = len(ME.ships_produced)
        opponent_produced = 0
        if TOTAL_N - my_produced > 0:
            opponent_produced = ceil(mean(filter(None, [len(other.ships_produced) for other in OTHER_PLAYERS])))
        return my_produced < opponent_produced or ROI > 0

    def produce_commands(self):
        """
        The high level of our bot.

        1. Assign ships to positions & dropoffs
        2. Maybe spawn ship
        3. Plan paths

        :return:
        """
        goals, mining_times, planned_dropoffs, costs = ResourceAllocation.goals_for_ships(
            self.opponent_model.get_next_positions())
        # log('allocated goals: {}'.format(goals))

        halite_available = ME.halite_amount
        spawning = False
        if halite_available >= constants.SHIP_COST and halite_available - sum(
                costs) >= constants.SHIP_COST and self.should_make_ship(goals):
            halite_available -= constants.SHIP_COST
            spawning = True
            # log('spawning')

        next_positions = PathPlanning.next_positions_for(self.opponent_model, goals, mining_times, spawning)
        # log('planned paths: {}'.format(next_positions))

        commands = []
        if spawning:
            commands.append(ME.shipyard.spawn())
        for i in range(N):
            if next_positions[i] is not None:
                commands.append(SHIPS[i].move(direction_between(SHIPS[i].pos, next_positions[i])))
            else:
                cost = constants.DROPOFF_COST - SHIPS[i].halite_amount - MAP[SHIPS[i].pos].halite_amount
                if halite_available >= cost:
                    commands.append(SHIPS[i].make_dropoff())
                    halite_available -= cost
                    # log('Making dropoff with {}'.format(SHIPS[i]))
                    planned_dropoffs.remove(SHIPS[i].pos)
                else:
                    commands.append(SHIPS[i].stay_still())

        return commands


class IncomeEstimation:
    @staticmethod
    def hpt_of(turns_remaining, turns_to_move, turns_to_dropoff, halite_on_board, space_left, halite_on_ground,
               inspiration_bonus):
        """
        The value function. Basically is just halite/time.

        Doesn't take into account halite burned to get there.
        Doesn't take into account opponents on the square.
        Doesn't accurately model mining time.
        Assumes ships will collect all the halite in the square.

        :param turns_remaining: int
        :param turns_to_move: int
        :param turns_to_dropoff: int
        :param halite_on_board: int
        :param space_left: int
        :param halite_on_ground: int
        :param inspiration_bonus: int
        :return: float
        """
        # TODO consider attacking opponent
        # TODO discount on number of enemy forces in area vs mine
        # TODO consider blocking opponent from dropoff
        if turns_to_move + turns_to_dropoff > turns_remaining:
            return 0, 0, 1

        if turns_to_dropoff == 0:
            if turns_to_move == 0:
                return halite_on_board, halite_on_board, 1
            else:
                return halite_on_board / turns_to_move + 1, halite_on_board, turns_to_move

        # TODO take into account movement cost?
        # TODO consider the HPT of attacking an enemy ship
        amount_gained = halite_on_ground
        if amount_gained > space_left:
            amount_gained = space_left
        space_left -= amount_gained
        inspiration_gained = inspiration_bonus
        if inspiration_gained > space_left:
            inspiration_gained = space_left
        space_left -= inspiration_gained

        gained = amount_gained + inspiration_gained

        # this block of code right here moved me from mid teens to top ten, and i was very surprised by it
        # basically this causes the ships to stay still more unless there is inspiration nearby
        # if you watch my bot you'll notice it clears things much more thoroughly than others
        if turns_to_move == 0:
            extract_time = 1
        else:
            extract_time = 3
            if inspiration_bonus > 0 or space_left == 0:
                extract_time /= 3

        time = turns_to_move + extract_time

        collect_hpt = gained / time
        # TODO dropoff bonus scale with amoutn gained
        dropoff_bonus = 1 / (turns_to_dropoff + 1)

        return collect_hpt + dropoff_bonus, gained, time

    @staticmethod
    def time_spent_mining(turns_to_dropoff, space_left, halite_on_ground, runner_up_assignment, extract_multiplier,
                          bonus_multiplier):
        """
        Figures out how long a ship will mine at a square for. A ship will mine until there's a more valuable
        position to be at.

        :param turns_to_dropoff: int
        :param space_left: int
        :param halite_on_ground: int
        :param runner_up_assignment: tuple
        :param extract_multiplier: float
        :param bonus_multiplier: float
        :return:
        """
        t = 0
        while space_left > 0 and halite_on_ground > 0:
            halite = constants.MAX_HALITE - space_left
            hpt, _, _ = IncomeEstimation.hpt_of(TURNS_REMAINING - t, 0, turns_to_dropoff, halite,
                                                space_left, halite_on_ground, halite_on_ground * bonus_multiplier)
            if hpt < runner_up_assignment[0] or hpt < halite / (turns_to_dropoff + 1):
                return t, halite_on_ground

            extracted = min(ceil(halite_on_ground * extract_multiplier), space_left)
            halite_on_ground -= extracted

            extracted *= 1 + bonus_multiplier
            space_left = max(space_left - extracted, 0)
            t += 1

        return t, halite_on_ground

    @staticmethod
    def roi():
        """
        The main function to handle ship spawning. Approximates the return we will get if we create another ship.

        Assumes all halite will be collected.
        Assumes all halite evenly among all the ships currently alive.
        Does not take into account halite in ship's cargo.

        :return: float
        """
        # TODO take into account growth curve?
        # TODO take into account efficiency?
        # TODO take into account turns remaining?
        # TODO take into account number of other players? not working well in 4 player mode
        expected_halite = N * HALITE_REMAINING / TOTAL_N if TOTAL_N > 0 else 0
        expected_halite_1 = (N + 1) * HALITE_REMAINING / (TOTAL_N + 1)
        halite_gained = expected_halite_1 - expected_halite
        return halite_gained - constants.SHIP_COST

    @staticmethod
    def collision_return(my_halite, their_halite):
        """
        The function for attacks and would be used for attacking if I finished that.

        Essentially: halite gained from other ship - amount of halite the ship is worth

        :param my_halite: int
        :param their_halite: int
        :return: int
        """
        expected_halite = N * HALITE_REMAINING / TOTAL_N if TOTAL_N > 0 else 0
        expected_halite_1 = (N - 1) * HALITE_REMAINING / (TOTAL_N - 2)
        return expected_halite_1 - expected_halite + (their_halite - my_halite)


class ResourceAllocation:
    @staticmethod
    def goals_for_ships(opponent_next_positions):
        """
        The first main part of the bot, assigns ships to positions:

            1. Get all possible assignments (ResourceAllocation.assignments)
            2. while there are still unscheduled ships
                2a. greedily take the best assignment
                2b. modify any remaining assignments to that same position (i.e. reduce their value)
            3. figure out if we want to make dropoffs
            4. assign ships to dropoffs
            5. redirect ships turning in to new dropoffs

        :param opponent_next_positions:
        :return: goals for ships, mining times for ships, planned dropoffs, costs of dropoffs
        """
        # TODO if we have way more ships than opponent ATTACK
        goals = [DROPOFF_BY_POS[SHIPS[i].pos] for i in range(N)]
        mining_times = [0 for i in range(N)]
        scheduled = [False] * N

        if ENDGAME:
            return goals, mining_times, [], []

        unscheduled = set(range(N))

        # log('building assignments')
        assignments = ResourceAllocation.assignments(unscheduled)

        # log('sorting assignments')
        assignments.sort(reverse=True)

        # log('gathering assignments')
        reservations_by_pos = defaultdict(int)
        halite_by_pos = {}
        while len(assignments) > 0:
            # pick the best assignment left & assign it
            hpt, i, pos, gained, distance, time = assignments[0]
            goals[i] = pos
            scheduled[i] = True
            it = filter(lambda a: a[1] == i, assignments)
            _, next_best = next(it), next(it)

            # figure out the time spent mining so we can adjust the other assignments for this position
            # this allows us to reserve the position for a certain amount of time and figure out how much halite
            # will be left.
            mining_times[i], halite_on_ground = IncomeEstimation.time_spent_mining(
                DROPOFF_DIST_BY_POS[pos], SHIPS[i].space_left, halite_by_pos.get(pos, MAP[pos].halite_amount),
                next_best, EXTRACT_MULTIPLIER_BY_POS[pos], BONUS_MULTIPLIER_BY_POS[pos])
            if pos not in DROPOFFS and pos in opponent_next_positions and MAP.dist(SHIPS[i].pos, pos) <= 1:
                halite_by_pos[pos] = halite_by_pos.get(pos, MAP[pos].halite_amount)
                halite_by_pos[pos] += SHIPS[i].halite_amount
                halite_by_pos[pos] += opponent_halite_next_to(pos)
                # halite_on_ground = halite_by_pos[pos]
            else:
                reservations_by_pos[pos] += mining_times[i] + 1
                halite_by_pos[pos] = halite_on_ground

            # keep every other assignment, modifying the assignments that are for the same position
            new_assignments = []
            inspiration_bonus = halite_on_ground * BONUS_MULTIPLIER_BY_POS[pos]
            reservations = reservations_by_pos[pos]
            dropoff_dist = DROPOFF_DIST_BY_POS[pos]
            for a in filter(lambda a: a[1] != i, assignments):
                if a[2] == pos:
                    # recalculate the value of this assignment
                    old_hpt, a_i, a_pos, a_gained, a_dist, a_time = a
                    new_hpt, gained, time = IncomeEstimation.hpt_of(
                        TURNS_REMAINING, a_dist + reservations, dropoff_dist, SHIPS[a_i].halite_amount,
                        SHIPS[a_i].space_left, halite_on_ground, inspiration_bonus)
                    new_assignments.append((new_hpt, a_i, a_pos, gained, a_dist, time))
                else:
                    new_assignments.append(a)
            assignments = sorted(new_assignments, reverse=True)

        # get any dropoffs we want to make
        # log('gathering potential dropoffs')
        score_by_dropoff, goals_by_dropoff = ResourceAllocation.get_potential_dropoffs(goals)
        # log(score_by_dropoff)
        # log(goals_by_dropoff)

        planned_dropoffs = []
        scheduled_dropoffs = []
        costs = []
        ships_for_dropoffs = set(range(N))
        if N > 10:
            # only make a dropoff if we have more than 1 ship going there
            # this should probably also check that there's more than 1 ship around the dropoff, but it doesn't
            planned_dropoffs = [drp for drp in goals_by_dropoff if goals_by_dropoff[drp] > 1]
            planned_dropoffs = sorted(planned_dropoffs, key=score_by_dropoff.get)

            # assign ships to each of the dropoffs
            for new_dropoff in planned_dropoffs:
                # log('dropoff position: {}'.format(new_dropoff))

                i = min(ships_for_dropoffs, key=lambda i: MAP.dist(SHIPS[i].pos, new_dropoff))
                costs.append(constants.DROPOFF_COST - SHIPS[i].halite_amount - MAP[new_dropoff].halite_amount)

                if ME.halite_amount >= costs[-1]:
                    # log('chosen ship: {}'.format(SHIPS[i]))
                    goals[i] = None if SHIPS[i].pos == new_dropoff else new_dropoff
                    ships_for_dropoffs.remove(i)
                    scheduled_dropoffs.append(new_dropoff)

        # redirect any ships turning in to the new dropoff
        for drp in scheduled_dropoffs:
            for i in ships_for_dropoffs:
                if goals[i] in DROPOFFS and MAP.dist(drp, SHIPS[i].pos) < DROPOFF_DIST_BY_POS[SHIPS[i].pos]:
                    goals[i] = drp

        return goals, mining_times, planned_dropoffs, costs

    @staticmethod
    def assignments(unscheduled):
        """
        Enumerates all assignments.

            1. for every position
                1a. for every ship
                    1ai. calculate value of sending ship here
            2. take the N largest assignments for each ship, where N is ~number of ships (don't need more assignments than that)

        Step 2 is key for letting us look at all possible squares instead of just nearest squares.

        In order to handle 64x64 with 150+ ships, I had to reduce the number of assignments per ship in step 2,
        once the number of ships gets above 100.

        Note: Doesn't calculate distance using A*, just assumes shortest distance will be taken. I don't think python could
        handle calling A* that often.

        :param unscheduled:
        :return:
        """
        # TODO don't assign to a position nearby with an enemy ship on it
        sxs = [SHIPS[i].pos[0] for i in unscheduled]
        sys = [SHIPS[i].pos[1] for i in unscheduled]
        halites = [SHIPS[i].halite_amount for i in unscheduled]
        spaces = [SHIPS[i].space_left for i in unscheduled]
        positions = MAP.positions
        if constants.NUM_PLAYERS == 4:
            positions = positions - {ship.pos for ship in OTHER_SHIPS}
            positions.update(DROPOFFS)
        P = len(positions)
        assignments_for_ship = [[None] * P for i in unscheduled]
        dist_table = MAP.distance_table
        for j, p in enumerate(positions):
            x, y = p
            halite_on_ground = MAP[p].halite_amount
            inspiration_bonus = halite_on_ground * BONUS_MULTIPLIER_BY_POS[p]
            dropoff_dist = DROPOFF_DIST_BY_POS[p]
            difficulty = DIFFICULTY[p]
            for i in unscheduled:
                d = dist_table[sxs[i] - x] + dist_table[sys[i] - y] + difficulty
                hpt, gained, time = IncomeEstimation.hpt_of(TURNS_REMAINING, d, dropoff_dist, halites[i], spaces[i],
                                                            halite_on_ground, inspiration_bonus)
                assignments_for_ship[i][j] = (hpt, i, p, gained, d, time)

        assignments = []
        if N > 0:
            max_per_ship = MAX_ASSIGNMENTS // N + 1
            n = min(N + 1, max_per_ship)
            # log('getting n={} largest assignments'.format(n))
            for i in unscheduled:
                assignments.extend(nlargest(n, assignments_for_ship[i]))
        return assignments

    @staticmethod
    def get_potential_dropoffs(goals):
        """
        Dropoff planning. I dislike this code a lot. I tried reworking it multiple times without success :(

            1. get the X positions with the largest amount of halite on them for candidates
                1a. if its 4p also add in positions around ships and their goals
            2. Get the dropoff score for each of these positions, and whether or not they can even be dropoffs
            3. Remove any conflicting dropoffs, taking the one with the highest score as the winner
            4. return any remaining

        :param goals:
        :return:
        """
        positions = set(nlargest(constants.WIDTH, MAP.positions, key=MAP.halite_at))

        # in 4p since there are more ships, I found i wasn't producing enough dropoffs without this.
        # i tried adding in 2p, but then was making too many dropoffs in not the best spots.
        if constants.NUM_PLAYERS == 4:
            for i in range(N):
                positions.update(all_neighbors(SHIPS[i].pos))
                positions.update(all_neighbors(goals[i]))

        # get biggest halite positions as dropoffs
        score_by_dropoff = {}
        goals_by_dropoff = {}
        for pos in positions:
            can, score, num_goals = ResourceAllocation.can_convert_to_dropoff(pos, goals)
            if can:
                score_by_dropoff[pos] = score
                goals_by_dropoff[pos] = num_goals

        # only take the biggest dropoff when there are multiple nearby
        # Note: this can actually be done in a better way if you just sort the dropoffs first, and only take a dropoff
        #   if it doesn't conflict with any others already taken.
        winners = set()
        for drp in score_by_dropoff:
            conflicting_winners = {w for w in winners if MAP.dist(w, drp) < 2 * DROPOFF_RADIUS}
            if len(conflicting_winners) == 0:
                winners.add(drp)
            elif all([score_by_dropoff[drp] > score_by_dropoff[w] for w in conflicting_winners]):
                winners -= conflicting_winners
                winners.add(drp)

        # select winners
        score_by_dropoff = {drp: score_by_dropoff[drp] for drp in winners}
        goals_by_dropoff = {drp: goals_by_dropoff[drp] for drp in winners}

        return score_by_dropoff, goals_by_dropoff

    @staticmethod
    def can_convert_to_dropoff(pos, goals):
        """
        Dropoff scoring and evaluation.

            1. Can't be within X distance of another dropoff of ours
            2. Has to have X * 4000 halite around it
            3. Allies have to be closer than opponents

        :param pos:
        :param goals:
        :return:
        """
        if MAP[pos].has_structure:
            return False, 0, 0

        for drp in DROPOFFS:
            if MAP.dist(pos, drp) <= 2 * DROPOFF_RADIUS:
                return False, 0, 0

        # give bonus for the halite on the dropoff
        halite_around = MAP[pos].halite_amount
        goals_around = 0
        for p in pos_around(pos, DROPOFF_RADIUS):
            halite_around += MAP[p].halite_amount
            if MAP[p].is_occupied and MAP[p].ship.owner == ME.id:
                halite_around += MAP[p].ship.halite_amount
            if p in goals:
                goals_around += 1

        ally_dist = sum(1 / (MAP.dist(s.pos, pos) + 1) for s in SHIPS)
        opponent_dists = []
        for owner in GAME.others:
            ships = GAME.players[owner].get_ships()
            opponent_dists.append(sum(1 / (MAP.dist(s.pos, pos) + 1) for s in ships))

        worthwhile = halite_around > DROPOFF_COST_MULT * constants.DROPOFF_COST
        allies_closer = all(ally_dist > opponent_dist for opponent_dist in opponent_dists)
        return worthwhile and allies_closer, halite_around, goals_around


class PathPlanning:
    @staticmethod
    def next_positions_for(opponent_model, goals, mining_times, spawning):
        """
        The second main part of the bot. Figuring out how to path each of the ships.

        1. reserve dropoff next timestep if spawning
        2. schedule ships to turn into dropoffs (no reservation added)
        3. reserve positions of ships that can't move
        4. reserve positions of ships that want to stay still
        5. plan the rest of the ship's paths

        Uses WHCA* for each of the ships. Basically A* with a window of time where it will check a reservation table.

        :param opponent_model:
        :param goals:
        :param mining_times:
        :param spawning:
        :return:
        """
        current = [SHIPS[i].pos for i in range(N)]
        next_positions = [current[i] for i in range(N)]
        reservations_outnumbered = defaultdict(set)
        reservations_self = defaultdict(set)
        scheduled = [False] * N
        conflicts = [0] * N
        distances = [0 if goals[i] is None else MAP.dist(current[i], goals[i]) for i in range(N)]

        # log('reserving other ship positions')

        def add_reservation(pos, time, is_own, outnumbered=True):
            """
            Used to add reservations to the reservations table. Only reserve positions on our dropoffs if its our own
            ship, otherwise ignore enemy ships, free halite!

            :param pos:
            :param time:
            :param is_own:
            :param outnumbered:
            :return:
            """
            # if not a dropoff, just add
            # if is a dropoff, add if enemy is reserving or if not endgame
            if pos in DROPOFFS:
                if not ENDGAME and is_own:
                    reservations_self[time].add(pos)
                    if outnumbered:
                        reservations_outnumbered[time].add(pos)
            else:
                if outnumbered:
                    reservations_outnumbered[time].add(pos)
                if is_own:
                    reservations_self[time].add(pos)

        def schedule(i, pos):
            """
            Schedules ship i to be at position next turn. this increments our conflict counter for ships.
            :param i:
            :param pos:
            :return:
            """
            if i is not None:
                next_positions[i] = pos
                scheduled[i] = True
            for j in range(N):
                if pos in all_neighbors(current[j]):
                    conflicts[j] += 1

        def plan_path(i):
            """
            Plan path for ship i
            :param i:
            :return:
            """
            my_halite = SHIPS[i].halite_amount

            # add reservations for ships that are right next to us so we don't collide
            # note: this does not add a reservation where we currently are. so other ships will still collide with us
            # i didn't have enough time to test it, and it was too passive locally.
            added = set()
            for n in cardinal_neighbors(current[i]):
                os = MAP[n].ship
                if os is not None and os.owner != ME.id and n not in DROPOFFS:
                    if n not in reservations_outnumbered[1] and IncomeEstimation.collision_return(my_halite,
                                                                                                  os.halite_amount) <= 0:
                        added.add(n)
                        for t in range(1, 9):
                            reservations_outnumbered[t].add(n)

            # first try to plan the path only avoiding enemy ships when we are outnumbered.
            # this means if we outnumber the opponent we don't have to worry about collisions
            # this prevents dropoff blocking, but makes our ships collide in really dumb situations
            # would've liked to have done this better
            path = PathPlanning.a_star(current[i], goals[i], my_halite, reservations_outnumbered)
            planned = True
            if path is None:
                # if we didn't find a path, ignore all enemy ships, and try to plan a path only avoiding our own ships
                path = PathPlanning.a_star(current[i], goals[i], my_halite, reservations_self)
                if path is None:
                    # if we still didn't find a path, try with only reservations on the next time step.
                    path = PathPlanning.a_star(current[i], goals[i], my_halite, reservations_self, window=2)
                    if path is None:
                        # if all else fails, just stay still, and we will probably collide with ourselves :(
                        path = [(current[i], 0), (current[i], 1)]
                        planned = False

            # reserve our position
            for raw_pos, t in path:
                add_reservation(raw_pos, t, is_own=True)

            # reserve our goal for the amount of time we will stay there
            if planned and goals[i] not in DROPOFFS:
                move_time = len(path)
                for t in range(move_time, move_time + mining_times[i]):
                    add_reservation(goals[i], t, is_own=True)
            schedule(i, path[1][0])

            for p in added:
                for t in range(1, 9):
                    reservations_outnumbered[t].remove(p)

        # add reservation if spawning
        if spawning:
            add_reservation(ME.shipyard.pos, 1, is_own=True)
            schedule(None, ME.shipyard.pos)

        # add reservations for enemy ship
        for opponent_ship in OTHER_SHIPS:
            add_reservation(opponent_ship.pos, 0, is_own=False)
            # TODO roi of losing ship?
            for next_pos in opponent_model.get_next_positions_for(opponent_ship):
                for t in range(1, 9):
                    add_reservation(next_pos, t, is_own=False,
                                    outnumbered=ALLIES_AROUND[next_pos] <= OPPONENTS_AROUND[next_pos])

        # avoid enemy dropoffs, free halite if they collide with us there
        for drp in OPPONENT_DROPOFFS:
            for t in range(0, 9):
                add_reservation(drp, t, is_own=False)

        # log('converting dropoffs')
        # schedule ships to turn into dropoffs
        for i in range(N):
            if goals[i] is None:
                scheduled[i] = True
                next_positions[i] = None
                # add_reservation(current[i], 1, is_own=True)

        unscheduled = [i for i in range(N) if not scheduled[i]]

        # log('locking stills')
        # schedule ships to stay still
        for i in unscheduled:
            cost = floor(MAP[current[i]].halite_amount / constants.MOVE_COST_RATIO)
            if cost > SHIPS[i].halite_amount:
                add_reservation(current[i], 1, is_own=True)
                schedule(i, current[i])

        unscheduled = [i for i in range(N) if not scheduled[i]]

        # log('planning stills')
        # schedule ships to stay still
        for i in unscheduled:
            if distances[i] == 0:
                plan_path(i)

        # log('planning paths')
        unscheduled = set(i for i in range(N) if not scheduled[i])
        number_closer = [0] * N
        for i in range(N):
            if goals[i] is not None:
                for j in range(N):
                    if MAP.dist(current[j], goals[i]) < distances[i]:
                        number_closer[i] += 1

        # plan the rest of the ships prioritizing this way:
        # 1. if any ship has 4 conflicts, plan them immediately. 4 conflicts means 4 of their cardinal moves are taken up
        # 2. plan any ships that are going to a dropoff
        # 3. ships that are closer to their goal get planned first
        # 4. ships that have fewer ships between them and their goal first
        # 5. ships that have more halite get planned first
        # 6. finally if there are still two equal ships (which there shouldn't be), order them by their id.
        while len(unscheduled) > 0:
            i = min(unscheduled, key=lambda i: (
                -(conflicts[i] >= 4), -int(goals[i] in DROPOFFS), distances[i], number_closer[i],
                -SHIPS[i].halite_amount, SHIPS[i].id))
            plan_path(i)
            unscheduled.remove(i)
        # log('paths planned')

        return next_positions

    @staticmethod
    def a_star(start, goal, starting_halite, reservation_table, window=8):
        """
        windowed hierarchical cooperative a*

        This is pretty much you're canonical A*, but with time added in as a third dimension.
        Additionally, when adding states into the open set, only add them if they aren't reserved and the time is still
        less than the window.

        Also halite tracking has been added.
        """

        start = normalize(start)
        goal = normalize(goal)

        heuristic_weight = 1 if goal in DROPOFFS else 2
        still_multiplier = 0 if goal in DROPOFFS else 1
        if constants.NUM_PLAYERS == 2:
            avoidance_weight = starting_halite / constants.MAX_HALITE
        else:
            avoidance_weight = 1 + constants.NUM_OPPONENTS * starting_halite / constants.MAX_HALITE

        if N > 100:
            window = min(window, 4)
            heuristic_weight = 2

        def heuristic(p):
            # heuristic should just be distance, but python is slow so have to make A* more greedy.
            # burning halite doesn't really matter much anyway
            return heuristic_weight * MAP.dist(p, goal)

        # log('{} -> {}'.format(start, goal))

        if start == goal and goal not in reservation_table[1]:
            return [(start, 0), (goal, 1)]

        closed_set = set()
        open_set = set()
        g_score = defaultdict(lambda: math.inf)
        h_score = defaultdict(lambda: math.inf)
        f_score = defaultdict(lambda: math.inf)
        came_from = {}
        halite_at = {}
        extractions_at = defaultdict(list)

        open_set.add((start, 0))
        g_score[(start, 0)] = 0
        h_score[(start, 0)] = heuristic(start)
        f_score[(start, 0)] = g_score[(start, 0)] + h_score[(start, 0)]
        halite_at[(start, 0)] = starting_halite
        extractions_at[(start, 0)] = []

        while len(open_set) > 0:
            # note: this should've been implemented using heappop and heappush for speed up, but i never thought about
            # it
            cpt = min(open_set, key=lambda pt: (f_score[pt], h_score[pt]))
            current, t = cpt

            halite_left = halite_at[cpt]

            halite_on_ground = MAP[current].halite_amount
            for pos, _, amt in extractions_at[cpt]:
                if pos == current:
                    halite_on_ground -= amt

            if current == goal and not (t < window and current in reservation_table[t]) and t > 0:
                return PathPlanning._reconstruct_path(came_from, cpt)

            # log('\t\tExpanding {}. f={} g={} h={} halite={} ground={}'.format(cpt, f_score[cpt], g_score[cpt],
            #                                                                   h_score[cpt], halite_left,
            #                                                                   halite_on_ground))

            open_set.remove(cpt)
            closed_set.add(cpt)

            raw_move_cost = floor(halite_on_ground / constants.MOVE_COST_RATIO)
            raw_extracted = ceil(halite_on_ground / constants.EXTRACT_RATIO)
            move_cost = raw_move_cost / constants.MAX_HALITE
            nt = t + 1
            avoid_mult = 1 if nt < window else 0

            neighbors = [current]
            if raw_move_cost <= halite_left:
                neighbors.extend(cardinal_neighbors(current))

            for neighbor in neighbors:
                npt = (neighbor, nt)

                if npt in closed_set or (nt < window and neighbor in reservation_table[nt]):
                    continue

                # TODO make dist actual dist, add new score for cost, and use cost to break ties
                dist = 1 - still_multiplier * move_cost if current == neighbor else 1 + move_cost
                g = g_score[cpt] + dist + avoid_mult * avoidance_weight * PROB_OCCUPIED[neighbor]

                if npt not in open_set:
                    open_set.add(npt)
                elif g >= g_score[npt]:
                    continue

                came_from[npt] = cpt
                g_score[npt] = g
                h_score[npt] = heuristic(neighbor)
                f_score[npt] = g_score[npt] + h_score[npt]

                if current == neighbor:
                    extracted = raw_extracted
                    halite_at[npt] = halite_left + extracted
                    extractions_at[npt] = extractions_at[cpt] + [(neighbor, nt, extracted)]
                else:
                    halite_at[npt] = halite_left - raw_move_cost
                    extractions_at[npt] = deepcopy(extractions_at[cpt])
                # log('-- Adding {} at {}. h={} g={}'.format(neighbor, nt, h_score[npt], g_score[npt]))

    @staticmethod
    def _reconstruct_path(prev_by_node, current):
        total_path = [current]
        while current in prev_by_node:
            current = prev_by_node[current]
            total_path.append(current)
        return list(reversed(total_path))


class OpponentModel:
    """
    A very simple opponent model. Assumes opponent will make any of the cardinal moves or stay still, unless they
    are out of halite.

    Gives slightly more probability to the opponent moving in the same direction they did last turn.
    """

    def __init__(self, n=10):
        self._n = n
        self._pos_by_ship = {}
        self._history_by_ship = {}
        self._moves_by_ship = {}
        self._predicted_by_ship = {}
        # self._potentials_by_ship = {}

        # self.tp = 0
        # self.fp = 0
        # self.tn = 0
        # self.fn = 0

    def get_next_positions_for(self, ship):
        return self._predicted_by_ship[ship]

    def get_next_positions(self):
        positions = set()
        for ship in self._predicted_by_ship:
            positions.update(self._predicted_by_ship[ship])
        return positions

    def moving_towards(self, ship, pos):
        last_dist = math.inf
        for old_pos in self._history_by_ship[ship][-2:]:
            d = MAP.dist(old_pos, pos)
            if d > last_dist:
                return False
            last_dist = d
        return True

    def prob_occupied(self):
        prob_by_pos = defaultdict(float)
        for ship, positions in self._predicted_by_ship.items():
            p = self._pos_by_ship[ship]
            score_by_pos = {p: 1 for p in positions}
            if N <= 100:
                for pos in positions:
                    if self.moving_towards(ship, pos):
                        score_by_pos[pos] += 1
                    if direction_between(p, pos) == self._moves_by_ship[ship][-1]:
                        score_by_pos[pos] += 1
            total_score = sum(score_by_pos.values())
            for pos in positions:
                prob_by_pos[pos] += score_by_pos[pos] / total_score

        # TODO do something else for frozen?
        for pos in prob_by_pos:
            if prob_by_pos[pos] > 1:
                prob_by_pos[pos] = 1

        for drp in DROPOFFS:
            prob_by_pos[drp] = 0

        return prob_by_pos

    def update_all(self):
        # predicted = self.get_next_positions()
        # actual = set(s.pos for s in OTHER_SHIPS)
        # potentials = set()
        # for ship, potentials in self._potentials_by_ship.items():
        #     potentials.update(potentials)

        # for pos in potentials:
        #     was_predicted = pos in predicted
        #     was_taken = pos in actual
        #     if was_predicted and was_taken:
        #         self.tp += 1
        #     elif was_predicted and not was_taken:
        #         self.fp += 1
        #     elif not was_predicted and was_taken:
        #         self.fn += 1
        #     else:
        #         self.tn += 1

        # total = self.tp + self.tn + self.fp + self.fn
        # if total > 0:
        #     mcc = self.tp * self.tn - self.fp * self.fn
        #     denom = (self.tp + self.fp) * (self.tp + self.fn) * (self.tn + self.fp) * (self.tn + self.fn)
        #     mcc /= math.sqrt(1 if denom == 0.0 else denom)
        # log('Opponent Model: tp={:.2f} tn={:.2f} fp={:.2f} fn={:.2f}'.format(
        #     100 * self.tp / total, 100 * self.tn / total, 100 * self.fp / total, 100 * self.fn / total))
        # log('Opponent Model: mcc={}'.format(mcc))

        for opponent_ship in OTHER_SHIPS:
            self.update(opponent_ship)

        # TODO make this check in a set, this is slow
        removed_ships = [ship for ship in self._predicted_by_ship if ship not in OTHER_SHIPS]
        for ship in removed_ships:
            del self._pos_by_ship[ship]
            del self._moves_by_ship[ship]
            del self._predicted_by_ship[ship]
            # del self._potentials_by_ship[ship]
            del self._history_by_ship[ship]

    def update(self, ship):
        if ship not in self._pos_by_ship:
            moves = [(0, 0)]
            history = [ship.pos]
        else:
            moves = self._moves_by_ship[ship]
            moves.append(direction_between(ship.pos, self._pos_by_ship[ship]))
            moves = moves[-self._n:]
            history = self._history_by_ship[ship]
            history.append(ship.pos)
            history = history[-self._n:]

        self._moves_by_ship[ship] = moves
        self._history_by_ship[ship] = history
        self._pos_by_ship[ship] = tuple(ship.pos)

        if ship.halite_amount < floor(MAP[ship.pos].halite_amount / constants.MOVE_COST_RATIO):
            predicted_moves = {(0, 0)}
        else:
            predicted_moves = list(constants.ALL_DIRECTIONS)

        self._predicted_by_ship[ship] = set(normalize(add(ship.pos, move)) for move in predicted_moves)
        # self._potentials_by_ship[ship] = all_neighbors(ship.pos)


def log(s):
    # logging.info('[{}] {}'.format(datetime.now(), s))
    pass


def normalize(p):
    """
    Normalizes a position
    :param p: tuple
    :return: tuple
    """
    x, y = p
    return x % constants.WIDTH, y % constants.HEIGHT


def add(a, b):
    """
    Adds two positions
    :param a: tuple
    :param b: tuple
    :return: tuple
    """
    ax, ay = a
    bx, by = b
    return ax + bx, ay + by


def cardinal_neighbors(p):
    """
    Cardinal neighbors of a position
    :param p: tuple
    :return: list[tuple]
    """
    return [normalize(add(p, d)) for d in constants.CARDINAL_DIRECTIONS]


def all_neighbors(p):
    """
    All neighbors of position (cardinal + stay still)
    :param p: tuple
    :return: set[tuple]
    """
    return set(normalize(add(p, d)) for d in constants.ALL_DIRECTIONS)


def direction_between(a, b):
    """
    The direction between two positions
    :param a: tuple
    :param b: tuple
    :return: tuple
    """
    for d in constants.ALL_DIRECTIONS:
        if normalize(add(a, d)) == normalize(b):
            return d


def pos_around(p, radius):
    """
    All of the positions around p within distance `radius`
    :param p: tuple
    :param radius: float
    :return: set[tuple]
    """
    px, py = p
    positions = set()
    for y in range(radius + 1):
        for x in range(radius + 1 - y):
            positions.add(normalize((px + x, py + y)))
            positions.add(normalize((px - x, py + y)))
            positions.add(normalize((px - x, py - y)))
            positions.add(normalize((px + x, py - y)))
    return positions


def opponent_halite_next_to(p):
    """
    The halite opponents are carrying adjacent to p
    :param p: tuple
    :return: float
    """
    halite = 0
    for p in pos_around(p, 1):
        if MAP[p].ship is not None and MAP[p].ship.owner != ME.id:
            halite += MAP[p].ship.halite_amount
    return halite


main()
