from twisted.trial import unittest
from twisted.internet.defer import succeed

from vumi.tests.utils import get_stubbed_worker
from vumi.workers.integrat.games import RockPaperScissorsGame, RockPaperScissorsWorker


class TestRockPaperScissorsGame(unittest.TestCase):
    def get_game(self, scores=None):
        game = RockPaperScissorsGame(5, 'p1')
        game.set_player_2('p2')
        if scores is not None:
            game.scores = scores
        return game

    def test_game_init(self):
        game = RockPaperScissorsGame(5, 'p1')
        self.assertEquals('p1', game.player_1)
        self.assertEquals(None, game.player_2)
        self.assertEquals((0, 0), game.scores)
        self.assertEquals(None, game.current_move)

        game.set_player_2('p2')
        self.assertEquals('p1', game.player_1)
        self.assertEquals('p2', game.player_2)
        self.assertEquals((0, 0), game.scores)
        self.assertEquals(None, game.current_move)

    def test_game_moves_draw(self):
        game = self.get_game((1,1))
        game.move('p1', 1)
        self.assertEquals(1, game.current_move)
        self.assertEquals((1, 1), game.scores)

        game.move('p2', 1)
        self.assertEquals(None, game.current_move)
        self.assertEquals((1, 1), game.scores)

    def test_game_moves_win(self):
        game = self.get_game((1,1))
        game.move('p1', 1)
        self.assertEquals(1, game.current_move)
        self.assertEquals((1, 1), game.scores)

        game.move('p2', 2)
        self.assertEquals(None, game.current_move)
        self.assertEquals((2, 1), game.scores)

    def test_game_moves_lose(self):
        game = self.get_game((1,1))
        game.move('p1', 1)
        self.assertEquals(1, game.current_move)
        self.assertEquals((1, 1), game.scores)

        game.move('p2', 3)
        self.assertEquals(None, game.current_move)
        self.assertEquals((1, 2), game.scores)



class RockPaperScissorsWorkerStub(RockPaperScissorsWorker):
    def reply(self, sid, message):
        self.replies.append(('reply', sid, message))

    def end(self, sid, message):
        self.replies.append(('end', sid, message))


class TestRockPaperScissorsWorker(unittest.TestCase):
    def get_worker(self):
        worker = get_stubbed_worker(RockPaperScissorsWorkerStub, {
                'transport_name': 'foo',
                'ussd_code': '99999',
                })
        worker.replies = []
        worker.startWorker()
        return worker

    def test_new_sessions(self):
        worker = self.get_worker()
        self.assertEquals({}, worker.games)
        self.assertEquals(None, worker.open_game)

        worker.new_session({'transport_session_id': 'sp1'})
        self.assertNotEquals(None, worker.open_game)
        game = worker.open_game
        self.assertEquals({'sp1': game}, worker.games)

        worker.new_session({'transport_session_id': 'sp2'})
        self.assertEquals(None, worker.open_game)
        self.assertEquals({'sp1': game, 'sp2': game}, worker.games)

        self.assertEquals(2, len(worker.replies))

    def test_moves(self):
        worker = self.get_worker()
        worker.new_session({'transport_session_id': 'sp1'})
        game = worker.open_game
        worker.new_session({'transport_session_id': 'sp2'})
        worker.replies = []

        worker.resume_session({'transport_session_id': 'sp2', 'message': '1'})
        self.assertEquals([], worker.replies)
        worker.resume_session({'transport_session_id': 'sp1', 'message': '2'})
        self.assertEquals(2, len(worker.replies))
        self.assertEquals((0,1), game.scores)