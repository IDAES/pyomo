#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright (c) 2008-2025
#  National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________
import pyomo.common.unittest as unittest

from pyomo.common.dependencies import mpi4py, mpi4py_available
from pyomo.contrib.pynumero.dependencies import (
    numpy_available,
    scipy_available,
    numpy as np,
)

SKIPTESTS = []
if numpy_available and scipy_available:
    from scipy.sparse import coo_matrix, bmat
else:
    SKIPTESTS.append("Pynumero needs scipy and numpy>=1.13.0 to run BlockMatrix tests")

if mpi4py_available:
    comm = mpi4py.MPI.COMM_WORLD
    if comm.Get_size() < 3:
        SKIPTESTS.append(
            "Pynumero needs at least 3 processes to run BlockVector MPI tests"
        )
else:
    SKIPTESTS.append("Pynumero needs mpi4py to run BlockVector MPI tests")

if not SKIPTESTS:
    from pyomo.contrib.pynumero.sparse import BlockVector
    from pyomo.contrib.pynumero.sparse.base_block import (
        vec_unary_ufuncs,
        vec_binary_ufuncs,
    )
    from pyomo.contrib.pynumero.sparse.mpi_block_vector import MPIBlockVector


@unittest.pytest.mark.mpi
class TestMPIBlockVector(unittest.TestCase):
    # Because the setUpClass is called before decorators around the
    # class itself, we need to put the skipIf on the class setup and not
    # the class.

    @classmethod
    @unittest.skipIf(SKIPTESTS, SKIPTESTS)
    def setUpClass(cls):
        # test problem 1

        v1 = MPIBlockVector(4, [0, 1, 0, 1], comm)

        rank = comm.Get_rank()
        if rank == 0:
            v1.set_block(0, np.ones(3))
            v1.set_block(2, np.ones(3))
        if rank == 1:
            v1.set_block(1, np.zeros(2))
            v1.set_block(3, np.ones(2))

        cls.v1 = v1
        v2 = MPIBlockVector(7, [0, 0, 1, 1, 2, 2, -1], comm)

        rank = comm.Get_rank()
        if rank == 0:
            v2.set_block(0, np.ones(2))
            v2.set_block(1, np.ones(2))
        if rank == 1:
            v2.set_block(2, np.zeros(3))
            v2.set_block(3, np.zeros(3))
        if rank == 2:
            v2.set_block(4, np.ones(4) * 2.0)
            v2.set_block(5, np.ones(4) * 2.0)
        v2.set_block(6, np.ones(2) * 3)

        cls.v2 = v2

    def test_nblocks(self):
        v1 = self.v1
        self.assertEqual(v1.nblocks, 4)
        v2 = self.v2
        self.assertEqual(v2.nblocks, 7)

    def test_bshape(self):
        v1 = self.v1
        self.assertEqual(v1.bshape[0], 4)
        v2 = self.v2
        self.assertEqual(v2.bshape[0], 7)

    def test_size(self):
        v1 = self.v1
        self.assertEqual(type(v1.size), int)
        self.assertEqual(v1.size, 10)
        v2 = self.v2
        self.assertEqual(type(v2.size), int)
        self.assertEqual(v2.size, 20)

    def test_shape(self):
        v1 = self.v1
        self.assertEqual(v1.shape[0], 10)
        v2 = self.v2
        self.assertEqual(v2.shape[0], 20)

    def test_ndim(self):
        v1 = self.v1
        self.assertEqual(v1.ndim, 1)

    def test_has_none(self):
        v = MPIBlockVector(4, [0, 1, 0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            self.assertTrue(v.has_none)
            v.set_block(0, np.ones(3))
            self.assertTrue(v.has_none)
            v.set_block(2, np.ones(3))
            self.assertFalse(v.has_none)
        elif rank == 1:
            self.assertTrue(v.has_none)
        else:
            self.assertFalse(v.has_none)
        self.assertFalse(self.v1.has_none)

    def test_any(self):
        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3))
        if rank == 1:
            v.set_block(1, np.zeros(3))
        self.assertTrue(v.any())
        self.assertTrue(self.v1.any())
        self.assertTrue(self.v2.any())

    def test_all(self):
        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3))
        if rank == 1:
            v.set_block(1, np.zeros(3))
        self.assertFalse(v.all())
        if rank == 1:
            v.set_block(1, np.ones(3))
        self.assertTrue(v.all())
        self.assertFalse(self.v1.all())
        self.assertFalse(self.v2.all())

    def test_min(self):
        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 10)
        if rank == 1:
            v.set_block(1, np.arange(3))
        self.assertEqual(v.min(), 0.0)
        if rank == 1:
            v.set_block(1, -np.arange(3))
        self.assertEqual(v.min(), -2.0)

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 10)
        if rank == 1:
            v.set_block(1, np.arange(3))
        v.set_block(2, -np.arange(6))
        self.assertEqual(v.min(), -5.0)
        self.assertEqual(self.v1.min(), 0.0)
        self.assertEqual(self.v2.min(), 0.0)

    def test_min_max_with_size0_blocks(self):
        v = MPIBlockVector(3, [0, 1, 2], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.array([8, 4, 7, 12]))
        if rank == 1:
            v.set_block(1, np.array([]))
        if rank == 2:
            v.set_block(2, np.array([5, 6, 3]))
        self.assertAlmostEqual(v.min(), 3)
        self.assertAlmostEqual(v.max(), 12)

        if rank == 0:
            v.set_block(0, np.array([np.inf, np.inf, np.inf, np.inf]))
        if rank == 2:
            v.set_block(2, np.array([np.inf, np.inf, np.inf]))
        self.assertEqual(v.min(), np.inf)
        self.assertEqual(v.max(), np.inf)
        v *= -1
        self.assertEqual(v.min(), -np.inf)
        self.assertEqual(v.max(), -np.inf)

        v = MPIBlockVector(3, [0, 1, 2], comm)
        v.set_block(rank, np.array([]))
        with self.assertRaisesRegex(ValueError, 'cannot get the min of a size 0 array'):
            v.min()
        with self.assertRaisesRegex(ValueError, 'cannot get the max of a size 0 array'):
            v.max()

    def test_max(self):
        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 10)
        if rank == 1:
            v.set_block(1, np.arange(3))
        self.assertEqual(v.max(), 12.0)

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 10)
        if rank == 1:
            v.set_block(1, np.arange(3))
        v.set_block(2, np.arange(60))
        self.assertEqual(v.max(), 59.0)
        self.assertEqual(self.v1.max(), 1.0)
        self.assertEqual(self.v2.max(), 3.0)

    def test_sum(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(3) + 3)
        v.set_block(2, np.arange(3) + 6)

        b = np.arange(9)
        self.assertEqual(b.sum(), v.sum())
        self.assertEqual(self.v1.sum(), 8)
        self.assertEqual(self.v2.sum(), 26)

    def test_prod(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(2))
        if rank == 1:
            v.set_block(1, np.ones(3))
        v.set_block(2, np.ones(3))
        self.assertEqual(1.0, v.prod())
        if rank == 1:
            v.set_block(1, np.ones(3) * 2)
        self.assertEqual(8.0, v.prod())
        if rank == 0:
            v.set_block(0, np.ones(2) * 3)
        self.assertEqual(72.0, v.prod())
        self.assertEqual(0.0, self.v1.prod())
        self.assertEqual(0.0, self.v2.prod())

    def test_conj(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(2))
        if rank == 1:
            v.set_block(1, np.ones(3))
        v.set_block(2, np.ones(3))
        res = v.conj()
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(res.nblocks, v.nblocks)
        for j in v.owned_blocks:
            self.assertTrue(np.allclose(res.get_block(j), v.get_block(j).conj()))

    def test_conjugate(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(2))
        if rank == 1:
            v.set_block(1, np.ones(3))
        v.set_block(2, np.ones(3))
        res = v.conjugate()
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(res.nblocks, v.nblocks)
        for j in v._owned_blocks:
            self.assertTrue(np.allclose(res.get_block(j), v.get_block(j).conjugate()))

    def test_nonzero(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.array([0, 1, 2]))
        if rank == 1:
            v.set_block(1, np.array([0, 0, 2]))
        v.set_block(2, np.ones(3))
        res = v.nonzero()[0]
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(res.nblocks, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(res.get_block(0), np.array([1, 2])))
        if rank == 1:
            self.assertTrue(np.allclose(res.get_block(1), np.array([2])))
        self.assertTrue(np.allclose(res.get_block(2), np.arange(3)))

        res = self.v1.nonzero()[0]
        if rank == 0:
            self.assertTrue(np.allclose(res.get_block(0), np.arange(3)))
            self.assertTrue(np.allclose(res.get_block(2), np.arange(3)))
        if rank == 1:
            self.assertTrue(np.allclose(res.get_block(1), np.arange(0)))
            self.assertTrue(np.allclose(res.get_block(3), np.arange(2)))

    def test_round(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 0.01)
        if rank == 1:
            v.set_block(1, np.arange(3) + 3 + 0.01)
        v.set_block(2, np.arange(3) + 6 + 0.01)

        res = v.round()
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(res.nblocks, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.arange(3), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.arange(3) + 3, res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(3) + 6, res.get_block(2)))

    def test_clip(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(3) + 3)
        v.set_block(2, np.arange(3) + 6)

        res = v.clip(min=2.0)
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(res.nblocks, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.array([2, 2, 2]), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.arange(3) + 3, res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(3) + 6, res.get_block(2)))

        res = v.clip(min=2.0, max=5.0)
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(res.nblocks, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.array([2, 2, 2]), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.array([3, 4, 5]), res.get_block(1)))
        self.assertTrue(np.allclose(np.array([5, 5, 5]), res.get_block(2)))

        v1 = self.v1
        res = v1.clip(max=0.5)
        if rank == 0:
            self.assertTrue(np.allclose(np.ones(3) * 0.5, res.get_block(0)))
            self.assertTrue(np.allclose(np.ones(3) * 0.5, res.get_block(2)))
        if rank == 1:
            self.assertTrue(np.allclose(np.zeros(2), res.get_block(1)))
            self.assertTrue(np.allclose(np.ones(2) * 0.5, res.get_block(3)))

    def test_compress(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        cond = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            cond.set_block(0, np.array([False, False, True]))
        if rank == 1:
            cond.set_block(1, np.array([True, True, True, False]))
        cond.set_block(2, np.array([True, True]))

        res = v.compress(cond)
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(res.nblocks, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.array([2]), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.array([0, 1, 2]), res.get_block(1)))
        self.assertTrue(np.allclose(np.array([0, 1]), res.get_block(2)))

        cond = BlockVector(3)
        cond.set_block(0, np.array([False, False, True]))
        cond.set_block(1, np.array([True, True, True, False]))
        cond.set_block(2, np.array([True, True]))

        with self.assertRaises(Exception) as context:
            res = v.compress(cond)

        with self.assertRaises(Exception) as context:
            res = v.compress(cond.flatten())

    def test_owned_blocks(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        owned = v.owned_blocks
        rank = comm.Get_rank()
        if rank == 0:
            self.assertTrue(np.allclose(np.array([0, 2]), owned))
        if rank == 1:
            self.assertTrue(np.allclose(np.array([1, 2]), owned))

        owned = self.v1.owned_blocks
        if rank == 0:
            self.assertTrue(np.allclose(np.array([0, 2]), owned))
        if rank == 1:
            self.assertTrue(np.allclose(np.array([1, 3]), owned))

    def test_shared_blocks(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        shared = v.shared_blocks
        self.assertTrue(np.allclose(np.array([2]), shared))

    def test_clone(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        vv = v.clone()
        self.assertTrue(isinstance(vv, MPIBlockVector))
        self.assertEqual(vv.nblocks, v.nblocks)
        self.assertTrue(np.allclose(vv.shared_blocks, v.shared_blocks))
        if rank == 0:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(0), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(1), v.get_block(1)))
        self.assertTrue(np.allclose(vv.get_block(2), v.get_block(2)))

    def test_copy(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        vv = v.copy()
        self.assertTrue(isinstance(vv, MPIBlockVector))
        self.assertEqual(vv.nblocks, v.nblocks)
        self.assertTrue(np.allclose(vv.shared_blocks, v.shared_blocks))
        if rank == 0:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(0), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(1), v.get_block(1)))
        self.assertTrue(np.allclose(vv.get_block(2), v.get_block(2)))

    def test_copyto(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        vv = MPIBlockVector(3, [0, 1, -1], comm)
        v.copyto(vv)

        self.assertTrue(isinstance(vv, MPIBlockVector))
        self.assertEqual(vv.nblocks, v.nblocks)
        self.assertTrue(np.allclose(vv.shared_blocks, v.shared_blocks))
        if rank == 0:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(0), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(1), v.get_block(1)))
        self.assertTrue(np.allclose(vv.get_block(2), v.get_block(2)))

    def test_fill(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        v.fill(7.0)
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        self.assertTrue(np.allclose(np.array([2]), v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(np.ones(3) * 7.0, v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.ones(4) * 7.0, v.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2) * 7.0, v.get_block(2)))

    def test_dot(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        all_v = np.concatenate([np.arange(3), np.arange(4), np.arange(2)])
        expected = all_v.dot(all_v)

        self.assertAlmostEqual(expected, v.dot(v))
        vv = BlockVector(3)
        vv.set_blocks([np.arange(3), np.arange(4), np.arange(2)])
        self.assertAlmostEqual(expected, v.dot(vv))
        self.assertAlmostEqual(expected, v.dot(vv.flatten()))

    def test_add(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        res = v + v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(3) * 2, res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(4) * 2, res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) * 2, res.get_block(2)))

        res = v + 5.0
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(3) + 5.0, res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(4) + 5.0, res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) + 5.0, res.get_block(2)))

        res = 5.0 + v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(3) + 5.0, res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(4) + 5.0, res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) + 5.0, res.get_block(2)))

    def test_sub(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        res = v - v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2), res.get_block(2)))

        res = 5.0 - v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(5.0 - np.arange(3), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(5.0 - np.arange(4), res.get_block(1)))
        self.assertTrue(np.allclose(5.0 - np.arange(2), res.get_block(2)))

        res = v - 5.0
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(3) - 5.0, res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(4) - 5.0, res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) - 5.0, res.get_block(2)))

    def test_mul(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        res = v * v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(3) * np.arange(3), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(4) * np.arange(4), res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) * np.arange(2), res.get_block(2)))

        res = v * 2.0
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(3) * 2.0, res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(4) * 2.0, res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) * 2.0, res.get_block(2)))

        res = 2.0 * v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(3) * 2.0, res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.arange(4) * 2.0, res.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) * 2.0, res.get_block(2)))

    def test_truediv(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 1.0)
        if rank == 1:
            v.set_block(1, np.arange(4) + 1.0)
        v.set_block(2, np.arange(2) + 1.0)

        res = v / v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2), res.get_block(2)))

        res = v / 2.0
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose((np.arange(3) + 1.0) / 2.0, res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose((np.arange(4) + 1.0) / 2.0, res.get_block(1)))
        self.assertTrue(np.allclose((np.arange(2) + 1.0) / 2.0, res.get_block(2)))

        res = 2.0 / v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(2.0 / (np.arange(3) + 1.0), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(2.0 / (np.arange(4) + 1.0), res.get_block(1)))
        self.assertTrue(np.allclose(2.0 / (np.arange(2) + 1.0), res.get_block(2)))

    def test_floordiv(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 1.0)
        if rank == 1:
            v.set_block(1, np.arange(4) + 1.0)
        v.set_block(2, np.arange(2) + 1.0)

        res = v // v
        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2), res.get_block(2)))

        bv = BlockVector(3)
        bv.set_blocks([np.arange(3) + 1.0, np.arange(4) + 1.0, np.arange(2) + 1.0])

        res1 = v // 2.0
        res2 = bv // 2.0
        self.assertTrue(isinstance(res1, MPIBlockVector))
        self.assertEqual(3, res1.nblocks)
        self.assertTrue(np.allclose(res1.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res1.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(res1.get_block(0), res2.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res1.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(res1.get_block(1), res2.get_block(1)))
        self.assertTrue(np.allclose(res1.get_block(2), res2.get_block(2)))

        res1 = 2.0 // v
        res2 = 2.0 // bv
        self.assertTrue(isinstance(res1, MPIBlockVector))
        self.assertEqual(3, res1.nblocks)
        self.assertTrue(np.allclose(res1.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res1.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(res1.get_block(0), res2.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res1.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(res1.get_block(1), res2.get_block(1)))
        self.assertTrue(np.allclose(res1.get_block(2), res2.get_block(2)))

    def test_isum(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        v += v
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.arange(3) * 2.0, v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.arange(4) * 2.0, v.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) * 2.0, v.get_block(2)))

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3, dtype='d'))
        if rank == 1:
            v.set_block(1, np.arange(4, dtype='d'))
        v.set_block(2, np.arange(2, dtype='d'))

        v += 7.0
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.arange(3) + 7.0, v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.arange(4) + 7.0, v.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) + 7.0, v.get_block(2)))

    def test_isub(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        v -= v
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.zeros(3), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.zeros(4), v.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2), v.get_block(2)))

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3, dtype='d'))
        if rank == 1:
            v.set_block(1, np.arange(4, dtype='d'))
        v.set_block(2, np.arange(2, dtype='d'))

        v -= 7.0
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.arange(3) - 7.0, v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.arange(4) - 7.0, v.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) - 7.0, v.get_block(2)))

    def test_imul(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        v *= v
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.arange(3) * np.arange(3), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.arange(4) * np.arange(4), v.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) * np.arange(2), v.get_block(2)))

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3, dtype='d'))
        if rank == 1:
            v.set_block(1, np.arange(4, dtype='d'))
        v.set_block(2, np.arange(2, dtype='d'))

        v *= 7.0
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.arange(3) * 7.0, v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.arange(4) * 7.0, v.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) * 7.0, v.get_block(2)))

    def test_itruediv(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 1.0)
        if rank == 1:
            v.set_block(1, np.arange(4) + 1.0)
        v.set_block(2, np.arange(2) + 1.0)

        v /= v
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.ones(3), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.ones(4), v.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2), v.get_block(2)))

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3) + 1.0)
        if rank == 1:
            v.set_block(1, np.arange(4) + 1.0)
        v.set_block(2, np.arange(2) + 1.0)

        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3, dtype='d'))
        if rank == 1:
            v.set_block(1, np.arange(4, dtype='d'))
        v.set_block(2, np.arange(2, dtype='d'))

        v /= 2.0
        self.assertTrue(isinstance(v, MPIBlockVector))
        self.assertEqual(3, v.nblocks)
        if rank == 0:
            self.assertTrue(np.allclose(np.arange(3) / 2.0, v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(np.arange(4) / 2.0, v.get_block(1)))
        self.assertTrue(np.allclose(np.arange(2) / 2.0, v.get_block(2)))

    def test_le(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 8)
        if rank == 1:
            v.set_block(1, np.ones(4) * 2)
        v.set_block(2, np.ones(2) * 4)

        v1 = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v1.set_block(0, np.ones(3) * 2)
        if rank == 1:
            v1.set_block(1, np.ones(4) * 8)
        v1.set_block(2, np.ones(2) * 4)

        res = v <= v1

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

        bv = BlockVector(3)
        bv.set_blocks([np.ones(3) * 2, np.ones(4) * 8, np.ones(2) * 4])

        with self.assertRaises(Exception) as context:
            res = v <= bv

        with self.assertRaises(Exception) as context:
            res = bv >= v

        with self.assertRaises(Exception) as context:
            res = v <= bv.flatten()

        with self.assertRaises(Exception) as context:
            res = bv.flatten() >= v

        res = v <= 3.0

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

        res = 3.0 >= v

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

    def test_lt(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 8)
        if rank == 1:
            v.set_block(1, np.ones(4) * 2)
        v.set_block(2, np.ones(2) * 4)

        v1 = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v1.set_block(0, np.ones(3) * 2)
        if rank == 1:
            v1.set_block(1, np.ones(4) * 8)
        v1.set_block(2, np.ones(2) * 4)

        res = v < v1

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

        bv = BlockVector(3)
        bv.set_blocks([np.ones(3) * 2, np.ones(4) * 8, np.ones(2) * 4])

        with self.assertRaises(Exception) as context:
            res = v < bv

        with self.assertRaises(Exception) as context:
            res = bv > v

        with self.assertRaises(Exception) as context:
            res = v < bv.flatten()

        with self.assertRaises(Exception) as context:
            res = bv.flatten() > v

        res = v < 3.0

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

        res = 3.0 > v

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

    def test_ge(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 8)
        if rank == 1:
            v.set_block(1, np.ones(4) * 2)
        v.set_block(2, np.ones(2) * 4)

        v1 = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v1.set_block(0, np.ones(3) * 2)
        if rank == 1:
            v1.set_block(1, np.ones(4) * 8)
        v1.set_block(2, np.ones(2) * 4)

        res = v >= v1

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

        bv = BlockVector(3)
        bv.set_blocks([np.ones(3) * 2, np.ones(4) * 8, np.ones(2) * 4])

        with self.assertRaises(Exception) as context:
            res = v >= bv

        with self.assertRaises(Exception) as context:
            res = bv <= v

        with self.assertRaises(Exception) as context:
            res = v >= bv.flatten()

        with self.assertRaises(Exception) as context:
            res = bv.flatten() <= v

        res = v >= 3.0

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

        res = 3.0 <= v

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

    def test_gt(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 8)
        if rank == 1:
            v.set_block(1, np.ones(4) * 2)
        v.set_block(2, np.ones(2) * 4)

        v1 = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v1.set_block(0, np.ones(3) * 2)
        if rank == 1:
            v1.set_block(1, np.ones(4) * 8)
        v1.set_block(2, np.ones(2) * 4)

        res = v > v1

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

        bv = BlockVector(3)
        bv.set_blocks([np.ones(3) * 2, np.ones(4) * 8, np.ones(2) * 4])

        with self.assertRaises(Exception) as context:
            res = v > bv

        with self.assertRaises(Exception) as context:
            res = bv < v

        with self.assertRaises(Exception) as context:
            res = v > bv.flatten()

        with self.assertRaises(Exception) as context:
            res = bv.flatten() < v

        res = v > 3.0

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

        res = 3.0 < v

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

    def test_eq(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 8)
        if rank == 1:
            v.set_block(1, np.ones(4) * 2)
        v.set_block(2, np.ones(2) * 4)

        v1 = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v1.set_block(0, np.ones(3) * 2)
        if rank == 1:
            v1.set_block(1, np.ones(4) * 8)
        v1.set_block(2, np.ones(2) * 4)

        res = v == v1

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

        bv = BlockVector(3)
        bv.set_blocks([np.ones(3) * 2, np.ones(4) * 8, np.ones(2) * 4])

        with self.assertRaises(Exception) as context:
            res = v == bv

        with self.assertRaises(Exception) as context:
            res = bv == v

        with self.assertRaises(Exception) as context:
            res = v == bv.flatten()

        with self.assertRaises(Exception) as context:
            res = bv.flatten() == v

        res = v == 8.0

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

        res = 8.0 == v

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

    def test_ne(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 8)
        if rank == 1:
            v.set_block(1, np.ones(4) * 2)
        v.set_block(2, np.ones(2) * 4)

        v1 = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v1.set_block(0, np.ones(3) * 2)
        if rank == 1:
            v1.set_block(1, np.ones(4) * 8)
        v1.set_block(2, np.ones(2) * 4)

        res = v != v1

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.zeros(2, dtype=bool), res.get_block(2)))

        bv = BlockVector(3)
        bv.set_blocks([np.ones(3) * 2, np.ones(4) * 8, np.ones(2) * 4])

        with self.assertRaises(Exception) as context:
            res = v != bv
        with self.assertRaises(Exception) as context:
            res = bv != v
        with self.assertRaises(Exception) as context:
            res = v != bv.flatten()
        with self.assertRaises(Exception) as context:
            res = bv.flatten() != v

        res = v != 8.0

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

        res = 8.0 != v

        self.assertTrue(isinstance(res, MPIBlockVector))
        self.assertEqual(3, res.nblocks)
        self.assertTrue(np.allclose(res.shared_blocks, v.shared_blocks))

        if rank == 0:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.zeros(3, dtype=bool), res.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(res.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(np.ones(4, dtype=bool), res.get_block(1)))
        self.assertTrue(np.allclose(np.ones(2, dtype=bool), res.get_block(2)))

    def test_unary_ufuncs(self):
        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 0.5)
        if rank == 1:
            v.set_block(1, np.ones(2) * 0.8)

        bv = BlockVector(2)
        a = np.ones(3) * 0.5
        b = np.ones(2) * 0.8
        bv.set_block(0, a)
        bv.set_block(1, b)

        _int_ufuncs = {np.invert, np.arccosh}

        bv2 = BlockVector(2)
        for fun in vec_unary_ufuncs:
            if fun in _int_ufuncs:
                continue

            bv2.set_block(0, fun(bv.get_block(0)))
            bv2.set_block(1, fun(bv.get_block(1)))
            res = fun(v)
            self.assertIsInstance(res, MPIBlockVector)
            self.assertEqual(res.nblocks, 2)
            for i in res.owned_blocks:
                self.assertTrue(np.allclose(res.get_block(i), bv2.get_block(i)))

        with self.assertRaises(Exception) as context:
            np.modf(v)

        with self.assertRaises(Exception) as context:
            np.cumsum(v)

        with self.assertRaises(Exception) as context:
            np.cumprod(v)

        with self.assertRaises(Exception) as context:
            np.cumproduct(v)

    def test_reduce_ufuncs(self):
        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 0.5)
        if rank == 1:
            v.set_block(1, np.ones(2) * 0.8)

        bv = BlockVector(2)
        bv.set_block(0, np.ones(3) * 0.5)
        bv.set_block(1, np.ones(2) * 0.8)

        reduce_funcs = [np.sum, np.max, np.min, np.prod, np.mean, np.all, np.any]
        for fun in reduce_funcs:
            self.assertAlmostEqual(fun(v), fun(bv.flatten()))

    def test_binary_ufuncs(self):
        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3) * 0.5)
        if rank == 1:
            v.set_block(1, np.ones(2) * 0.8)

        v2 = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v2.set_block(0, np.ones(3) * 3.0)
        if rank == 1:
            v2.set_block(1, np.ones(2) * 2.8)

        bv = BlockVector(2)
        bv.set_block(0, np.ones(3) * 0.5)
        bv.set_block(1, np.ones(2) * 0.8)

        bv2 = BlockVector(2)
        bv2.set_block(0, np.ones(3) * 3.0)
        bv2.set_block(1, np.ones(2) * 2.8)

        _int_ufuncs = {
            np.gcd,
            np.lcm,
            np.ldexp,
            np.left_shift,
            np.right_shift,
            np.bitwise_and,
            np.bitwise_or,
            np.bitwise_xor,
        }

        for fun in vec_binary_ufuncs:
            if fun in _int_ufuncs:
                continue

            serial_res = fun(bv, bv2)
            res = fun(v, v2)

            self.assertIsInstance(res, MPIBlockVector)
            self.assertEqual(res.nblocks, 2)
            for i in res.owned_blocks:
                self.assertTrue(np.allclose(res.get_block(i), serial_res.get_block(i)))

            serial_res = fun(bv, bv2)
            with self.assertRaises(Exception) as context:
                res = fun(v, bv2)

            serial_res = fun(bv, bv2)
            with self.assertRaises(Exception) as context:
                res = fun(bv, v2)

            serial_res = fun(bv, 2.0)
            res = fun(v, 2.0)

            self.assertIsInstance(res, MPIBlockVector)
            self.assertEqual(res.nblocks, 2)
            for i in res.owned_blocks:
                self.assertTrue(np.allclose(res.get_block(i), serial_res.get_block(i)))

            serial_res = fun(2.0, bv)
            res = fun(2.0, v)

            self.assertIsInstance(res, MPIBlockVector)
            self.assertEqual(res.nblocks, 2)
            for i in res.owned_blocks:
                self.assertTrue(np.allclose(res.get_block(i), serial_res.get_block(i)))

        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3, dtype=bool))
        if rank == 1:
            v.set_block(1, np.ones(2, dtype=bool))

        v2 = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v2.set_block(0, np.zeros(3, dtype=bool))
        if rank == 1:
            v2.set_block(1, np.zeros(2, dtype=bool))

        bv = BlockVector(2)
        bv.set_block(0, np.ones(3, dtype=bool))
        bv.set_block(1, np.ones(2, dtype=bool))

        bv2 = BlockVector(2)
        bv2.set_block(0, np.zeros(3, dtype=bool))
        bv2.set_block(1, np.zeros(2, dtype=bool))

        binary_ufuncs = [np.logical_and, np.logical_or, np.logical_xor]
        for fun in binary_ufuncs:
            serial_res = fun(bv, bv2)
            res = fun(v, v2)
            self.assertIsInstance(res, MPIBlockVector)
            self.assertEqual(res.nblocks, 2)
            for i in res.owned_blocks:
                self.assertTrue(np.allclose(res.get_block(i), serial_res.get_block(i)))

            serial_res = fun(bv, bv2)
            with self.assertRaises(Exception) as context:
                res = fun(v, bv2)

            serial_res = fun(bv, bv2)
            with self.assertRaises(Exception) as context:
                res = fun(bv, v2)

    def test_contains(self):
        v = MPIBlockVector(2, [0, 1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.ones(3))
        if rank == 1:
            v.set_block(1, np.zeros(2))

        self.assertTrue(0 in v)
        self.assertFalse(3 in v)

    def test_copyfrom(self):
        v = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            v.set_block(0, np.arange(3))
        if rank == 1:
            v.set_block(1, np.arange(4))
        v.set_block(2, np.arange(2))

        bv = BlockVector(3)
        bv.set_blocks([np.arange(3), np.arange(4), np.arange(2)])
        vv = MPIBlockVector(3, [0, 1, -1], comm)
        vv.copyfrom(v)

        self.assertTrue(isinstance(vv, MPIBlockVector))
        self.assertEqual(vv.nblocks, v.nblocks)
        self.assertTrue(np.allclose(vv.shared_blocks, v.shared_blocks))
        if rank == 0:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(0), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(1), v.get_block(1)))
        self.assertTrue(np.allclose(vv.get_block(2), v.get_block(2)))

        vv = MPIBlockVector(3, [0, 1, -1], comm)
        vv.copyfrom(bv)

        self.assertTrue(isinstance(vv, MPIBlockVector))
        self.assertEqual(vv.nblocks, v.nblocks)
        self.assertTrue(np.allclose(vv.shared_blocks, v.shared_blocks))
        if rank == 0:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(0), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(1), v.get_block(1)))
        self.assertTrue(np.allclose(vv.get_block(2), v.get_block(2)))

        vv = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            vv.set_block(0, np.arange(3) + 1)
        if rank == 1:
            vv.set_block(1, np.arange(4) + 1)
        vv.set_block(2, np.arange(2) + 1)

        vv.copyfrom(bv)

        self.assertTrue(isinstance(vv, MPIBlockVector))
        self.assertEqual(vv.nblocks, v.nblocks)
        self.assertTrue(np.allclose(vv.shared_blocks, v.shared_blocks))
        if rank == 0:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(0), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(1), v.get_block(1)))
        self.assertTrue(np.allclose(vv.get_block(2), v.get_block(2)))

        vv = MPIBlockVector(3, [0, 1, -1], comm)
        rank = comm.Get_rank()
        if rank == 0:
            vv.set_block(0, np.arange(3) + 1)
        if rank == 1:
            vv.set_block(1, np.arange(4) + 1)
        vv.set_block(2, np.arange(2) + 1)

        vv.copyfrom(v)

        self.assertTrue(isinstance(vv, MPIBlockVector))
        self.assertEqual(vv.nblocks, v.nblocks)
        self.assertTrue(np.allclose(vv.shared_blocks, v.shared_blocks))
        if rank == 0:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(0), v.get_block(0)))
        if rank == 1:
            self.assertTrue(np.allclose(vv.owned_blocks, v.owned_blocks))
            self.assertTrue(np.allclose(vv.get_block(1), v.get_block(1)))
        self.assertTrue(np.allclose(vv.get_block(2), v.get_block(2)))


if __name__ == '__main__':
    unittest.main()
