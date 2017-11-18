from sympy import flatten, Eq, zeros, Matrix, eye, S, sqrt, Equality, MatrixSymbol, nsimplify, Abs, Piecewise, GreaterThan, Float
from sympy import Idx
from opensbli.core.kernel import Kernel, ConstantsToDeclare
from opensbli.core.opensbliobjects import DataSet, ConstantIndexed
from opensbli.core.datatypes import Int
from opensbli.core.grid import GridVariable
from opensbli.physical_models.ns_physics import NSphysics
from opensbli.utilities.helperfunctions import dot, get_min_max_halo_values, increment_dataset
from sympy.functions.elementary.piecewise import ExprCondPair
from opensbli.core.weno_opensbli import ShockCapturing
side_names = {0: 'left', 1: 'right'}
from sympy import pprint


class Exchange(object):
    pass


class ModifyCentralDerivative(object):
    """ A place holder for the boundary conditions on which the central derivative should be modified"""
    pass


class ExchangeSelf(Exchange):

    """ Defines data exchange on the same block. """

    def __init__(self, block, direction, side):
        # Range of evaluation (i.e. the grid points, including the halo points, over which the computation should be performed).
        self.computation_name = "exchange"
        self.block_number = block.blocknumber
        self.block_name = block.blockname
        self.direction = direction
        self.side = side_names[side]
        return

    @property
    def name(self):
        return "%s%d" % (self.computation_name, self.number)

    def set_arrays(self, arrays):
        self.transfer_arrays = flatten(arrays)
        self.from_arrays = flatten(arrays)
        self.to_arrays = flatten(arrays)
        return

    def set_transfer_from(self, transfer):
        self.transfer_from = transfer
        return

    def set_transfer_to(self, transfer):
        self.transfer_to = transfer
        return

    def set_transfer_size(self, size):
        self.transfer_size = size
        return

    @property
    def algorithm_node_name(self):
        name = "Boundary_exchange_block_%d_direction%d_side%s" % (self.block_number, self.direction, self.side)
        return name

    def write_latex(self, latex):
        latex.write_string("This is an exchange self kernel on variables %s\\\\" % ', '.join([str(a) for a in self.transfer_arrays]))
        return

    @property
    def opsc_code(self):
        """The string for calling the boundary condition in OPSC is update while creating
        the code for exchanging data
        """
        return [self.call_name]


class BoundaryConditionTypes(object):

    """ Base class for boundary conditions. We store the name of the boundary condition and type of the boundary for debugging purposes only.
    The application of the boundary conditions requires this base class on the grid.
    Computations can be computational Kernels or Exchange type objects."""

    def set_boundary_types(self, types, block):
        """ Adds the boundary types of the grid """
        # convert the list of types into a list of tuples
        types = flatten(types)
        self.check_boundarysizes_ndim_match(types)
        for t in types:
            t.convert_dataobject_to_dataset(block)
        it = iter(types)
        self.boundary_types = zip(it, it)
        return

    def check_boundarysizes_ndim_match(self, types):
        if len(types) != self.ndim*2:
            raise ValueError("Boundaries provided should match the number of dimension")
        return

    def check_modify_central(self):
        modify = {}
        for no, val in enumerate(self.boundary_types):
            left = val[0]
            right = val[1]
            if isinstance(left, ModifyCentralDerivative):
                if no in modify:
                    modify[no][0] = left
                else:
                    modify[no] = [left, None]
            if isinstance(right, ModifyCentralDerivative):
                if no in modify:
                    modify[no][1] = right
                else:
                    modify[no] = [None, right]
        return modify


class BoundaryConditionBase(object):
    """ Base class for common functionality between all boundary conditions.
    :arg int boundary_direction: Spatial direction to apply boundary condition to.
    :arg int side: Side 0 or 1 to apply the boundary condition for a given direction.
    :arg bool plane: True/False: Apply boundary condition to full range/split range only."""
    def __init__(self, boundary_direction, side, plane):
        if plane:
            self.full_plane = True
        else:
            self.full_plane = False
        self.direction = boundary_direction
        self.side = side
        self.equations = None
        return

    def convert_dataobject_to_dataset(self, block):
        """ Converts DataObjects to DataSets.
        :arg object block. OpenSBLI SimulationBlock."""
        if isinstance(self, SplitBoundaryConditionBlock):
            for bc in self.bc_types:
                if bc.equations:
                    bc.equations = block.dataobjects_to_datasets_on_block(bc.equations)
        else:
            if self.equations:
                self.equations = block.dataobjects_to_datasets_on_block(self.equations)
        return

    def convert_dataset_base_expr_to_datasets(self, expression, index): ### CHANGE THE NAME OF THIS? It is wrong.
        """ Converts an expression containing DataSetBases to Datasets and updates locations.
        :arg object expression: Symbolic expression. 
        :arg int index: Index to increment the DataSet by.
        returns: object: expression: Updated symbolic expression."""
        for a in expression.atoms(DataSet):
            b = a.base
            expression = expression.xreplace({a: b[index]})
        return expression

    def generate_boundary_kernel(self, block, bc_name):
        if self.full_plane:
            return self.bc_plane_kernel(block, bc_name)
        else:
            return self.arbitrary_bc_plane_kernel(block, bc_name)

    def arbitrary_bc_plane_kernel(self, block, bc_name):
        bc_name = self.bc_name
        direction, side, split_number = self.direction, self.side, self.split_number
        kernel = Kernel(block, computation_name="%s bc direction-%d side-%d split-%d" % (bc_name, direction, side, split_number))
        print kernel.computation_name
        numbers = Idx('no', 2*block.ndim)
        ranges = ConstantIndexed('split_range_%d%d%d'%(direction, side, split_number), numbers)
        ranges.datatype = Int()
        kernel.ranges = ranges
        halo_ranges = ConstantIndexed('split_halo_range_%d%d%d'%(direction, side, split_number), numbers)
        halo_ranges.datatype = Int()
        kernel.halo_ranges = halo_ranges
        ConstantsToDeclare.add_constant(ranges)
        ConstantsToDeclare.add_constant(halo_ranges)
        halo_values = self.get_halo_values(block)
        return halo_values, kernel


    def set_kernel_range(self, kernel, block):
        """ Sets the boundary condition kernel ranges based on direction and side.
        :arg object kernel: Computational boundary condition kernel.
        :arg object block: The SimulationBlock the boundary conditions are used on.
        :returns kernel: The computational kernel with updated ranges."""
        side, direction = self.side, self.direction
        kernel.ranges = block.ranges[:]
        if side == 0:
            left = 0
            right = 1
        elif side == 1:
            left = -1
            right = 0
        kernel.ranges[direction] = [block.ranges[direction][side]+left, block.ranges[direction][side]+right]
        return kernel

    def get_halo_values(self, block):
        """ Gets the maximum numerical halo values.
        :arg object block: The SimulationBlock the boundary conditions are used on.
        :returns halo_values: Numerical values of the halos in all directions."""
        halo_values = []
        halo_objects = block.boundary_halos
        for i in range(len(halo_objects)):
            halo_m, halo_p = get_min_max_halo_values(halo_objects)
            halo_m, halo_p = halo_m[0], halo_p[0]
            halo_values.append([halo_m, halo_p])
        return halo_values

    def bc_plane_kernel(self, block, bc_name):
        direction, side = self.direction, self.side
        kernel = Kernel(block, computation_name="%s boundary dir%d side%d" % (bc_name, direction, side))
        kernel = self.set_kernel_range(kernel, block)
        halo_values = self.get_halo_values(block)
        # Add the halos to the kernel in directions not equal to boundary direction
        for i in [x for x in range(block.ndim) if x != direction]:
            kernel.halo_ranges[i][0] = block.boundary_halos[i][0]
            kernel.halo_ranges[i][1] = block.boundary_halos[i][1]
        return halo_values, kernel

    def create_boundary_equations(self, left_arrays, right_arrays, transfer_indices):
        direction = self.direction
        if isinstance(left_arrays, list):
            loc = list(left_arrays[0].indices)
        else:
            loc = left_arrays.indices
        final_equations = []
        for index in transfer_indices:
            array_equations = []
            loc_lhs, loc_rhs = loc[:], loc[:]
            loc_lhs[direction] += index[0]
            loc_rhs[direction] += index[1]
            for left, right in zip(left_arrays, right_arrays):
                left = self.convert_dataset_base_expr_to_datasets(left, loc_lhs)
                right = self.convert_dataset_base_expr_to_datasets(right, loc_rhs)
                array_equations += [Eq(left, right, evaluate=False)]
            final_equations += array_equations
        return final_equations

    def set_side_factor(self):
        """ Sets the +/- 1 side factors for boundary condition halo numbering."""
        if self.side == 0:
            from_side_factor = -1
            to_side_factor = 1
        elif self.side == 1:
            from_side_factor = 1
            to_side_factor = -1
        return from_side_factor, to_side_factor


class SplitBoundaryConditionBlock(BoundaryConditionBase):
    def __init__(self, boundary_direction, side, bcs, plane=False):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_types = bcs
        return
    
    def pre_process_bc(self):
        return

    def apply(self, arrays, block):
        kernels = []
        for no, bc in enumerate(self.bc_types):
            bc.full_plane = False
            bc.split_number = no
            print type(bc)
            kernels.append(bc.apply(arrays, block))
        return kernels


class PeriodicBoundaryConditionBlock(BoundaryConditionBase):
    """ Applies an exchange periodic boundary condition.
    :arg int boundary_direction: Spatial direction to apply boundary condition to.
    :arg int side: Side 0 or 1 to apply the boundary condition for a given direction.
    :arg bool plane: True/False: Apply boundary condition to full range/split range only."""
    def __init__(self, boundary_direction, side, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        return

    def halos(self):
        return True

    def apply(self, arrays, block):
        # Get the exchanges which form the computations.
        if self.full_plane:
            exchange = self.get_exchange_plane(arrays, block)
        return exchange

    def get_exchange_plane(self, arrays, block):
        """ Create the exchange computations which copy the block point values to/from the periodic domain boundaries. """

        # Create a kernel this is a neater way to implement the transfers
        ker = Kernel(block)
        halos = self.get_halo_values(block)
        size, from_location, to_location = self.get_transfers(block.Idxed_shape, halos)
        ex = ExchangeSelf(block, self.direction, self.side)
        ex.set_transfer_size(size)
        ex.set_transfer_from(from_location)
        ex.set_transfer_to(to_location)
        ex.set_arrays(arrays)
        ex.number = ker.kernel_no
        return ex

    def get_transfers(self, idx, halos):
        boundary_direction, side = self.direction, self.side
        transfer_from = [d[0] for d in halos]
        transfer_to = [d[0] for d in halos]
        if side == 0:
            transfer_from[boundary_direction] = idx[boundary_direction].lower
            transfer_to[boundary_direction] = idx[boundary_direction].upper
        else:
            transfer_from[boundary_direction] = idx[boundary_direction].upper + halos[boundary_direction][0]
            transfer_to[boundary_direction] = idx[boundary_direction].lower + halos[boundary_direction][0]

        transfer_size = Matrix([i.upper + i.lower for i in idx]) + \
            Matrix([abs(dire[0]) + abs(dire[1]) for dire in halos])
        transfer_size[boundary_direction] = abs(halos[boundary_direction][side])
        return transfer_size, transfer_from, transfer_to


class DirichletBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
    """ Applies a constant value Dirichlet boundary condition.
    :arg int boundary_direction: Spatial direction to apply boundary condition to.
    :arg int side: Side 0 or 1 to apply the boundary condition for a given direction.
    :arg list equations: OpenSBLI equations to enforce on the boundary.
    :arg object scheme: Boundary scheme if required, defaults to Carpenter boundary treatment.
    :arg bool plane: True/False: Apply boundary condition to full range/split range only."""
    def __init__(self, boundary_direction, side, equations, scheme=None, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_name = 'Dirichlet'
        self.equations = equations
        if not scheme:
            self.modification_scheme = Carpenter()
        else:
            self.modification_scheme = scheme
        return


    def halos(self):
        return True

    def apply(self, arrays, block):
        direction, side = self.direction, self.side
        halos, kernel = self.generate_boundary_kernel(block, self.bc_name)
        # Dirichlet set on the boundary
        kernel.add_equation(self.equations)
        # Change ranges if using split BC
        if isinstance(kernel.halo_ranges, ConstantIndexed):
            # Manually set Dirichlet into the halo range of this side
            halo_object = kernel.halo_ranges
            halo_object._value[2*direction + side] = halos[direction][side]
        else: # Not using split BC, halos should be updated
            kernel.halo_ranges[direction][side] = block.boundary_halos[direction][side]
        kernel.update_block_datasets(block)
        return kernel


class SymmetryBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
    """ Applies a symmetry condition on the boundary, normal velocity components set/evaluate to zero.

    :arg int boundary_direction: Spatial direction to apply boundary condition to.
    :arg int side: Side 0 or 1 to apply the boundary condition for a given direction.
    :arg object scheme: Boundary scheme if required, defaults to Carpenter boundary treatment.
    :arg bool plane: True/False: Apply boundary condition to full range/split range only."""

    def __init__(self, boundary_direction, side, scheme=None, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_name = 'Symmetry'
        if not scheme:
            self.modification_scheme = Carpenter()
        else:
            self.modification_scheme = scheme
        return

    def apply(self, arrays, block):
        fdmteric = block.fd_metrics
        direction, side = self.direction, self.side
        direction_metric = Matrix(fdmteric[direction, :])
        from sympy import pprint
        normalisation = sqrt(sum([a**2 for a in direction_metric]))
        unit_normals = direction_metric/normalisation
        lhs_eqns = flatten(arrays)
        boundary_values = []
        rhs_eqns = []
        for ar in arrays:
            if isinstance(ar, list):
                contra_variant_vector = unit_normals.dot(Matrix(ar))
                transformed_vector = Matrix(ar).T - 2.*contra_variant_vector*unit_normals
                rhs_eqns += flatten(transformed_vector)
                # Later move this to an inviscid wall boundary condition
                transformed_vector = Matrix(ar).T - contra_variant_vector*unit_normals
                boundary_values += flatten(transformed_vector)
            else:
                rhs_eqns += [ar]
                boundary_values += [ar]
        halos, kernel = self.generate_boundary_kernel(block, self.bc_name)
        from_side_factor, to_side_factor = self.set_side_factor()

        transfer_indices = [tuple([from_side_factor*t, to_side_factor*t]) for t in range(1, abs(halos[direction][side]) + 1)]
        final_equations = self.create_boundary_equations(lhs_eqns, rhs_eqns, transfer_indices)
        transfer_indices = [tuple([0, 1])]
        final_equations += self.create_boundary_equations(lhs_eqns, boundary_values, transfer_indices)
        kernel.add_equation(final_equations)
        kernel.update_block_datasets(block)
        return kernel


class Carpenter(object):
    """ 4th order one-sided Carpenter boundary treatment (https://doi.org/10.1006/jcph.1998.6114). 
    If a boundary condition is an instance of
    ModifyCentralDerivative, central derivatives are replaced at that domain boundary by the Carpenter scheme."""
    def __init__(self):
        self.bc4_coefficients = self.carp4_coefficients()
        self.bc4_symbols = self.carp4_symbols()
        self.bc4_2_symbols = self.second_der_symbols()
        self.bc4_2_coefficients = self.second_der_coefficients()
        return

    def function_points(self, expression, direction, side):
        f_matrix = zeros(6, 6)
        loc = list(list(expression.atoms(DataSet))[0].indices)
        for shift in range(6):
            func_points = []
            for index in range(6):
                new_loc = loc[:]
                new_loc[direction] += index - shift
                for dset in expression.atoms(DataSet):
                    expression = expression.replace(dset, dset.base[new_loc])
                func_points.append(expression)
            f_matrix[:, shift] = func_points
        if side == 0:
            f_matrix = f_matrix[:, 0:4]
        elif side == 1:
            f_matrix = f_matrix.transpose()[:, 0:4]
        else:
            raise NotImplementedError("Side must be 0 or 1")
        return f_matrix

    def weight_function_points(self, func_points, direction, order, block, side, char_BC=False):
        if order == 1:
            h = S.One  # The division of delta is now applied in central derivative to reduce the divisions
            if side == 1:
                h = -S.One*h  # Modify the first derivatives for side ==1
            if char_BC:
                weighted = h*(self.bc4_symbols[0, :]*func_points)
            else:
                weighted = zeros(4, 1)
                for i in range(4):
                    weighted[i] = h*(self.bc4_coefficients[i, :]*func_points[:, i])
        elif order == 2:
            h_sq = S.One  # The division of delta**2 is now applied in central derivative to reduce the divisions
            weighted = zeros(2, 1)
            for i in range(2):
                weighted[i] = h_sq*(self.bc4_2_coefficients[i, :]*func_points[0:5, i])
        else:
            raise NotImplementedError("Only 1st and 2nd derivatives implemented")
        return weighted

    def expr_cond_pairs(self, fn, direction, side, order, block):
        fn_pts = self.function_points(fn, direction, side)
        derivatives = self.weight_function_points(fn_pts, direction, order, block, side)
        idx = block.grid_indexes[direction]
        if side == 0:
            mul_factor = 1
            start = block.ranges[direction][side]
        else:
            mul_factor = -1
            start = block.ranges[direction][side] - 1
        ecs = []
        # Commenting out creating different kernels for the Carpenter bc's
        # ranges = []
        for no, d in enumerate(derivatives):
            loc = start + mul_factor*no
            # ranges += [loc] # Commenting out creating different kernels for the Carpenter bc's
            ecs += [ExprCondPair(d, Equality(idx, loc))]
        # Commenting out creating different kernels for the Carpenter bc's
        """if side != 0:
            ranges = list(reversed(ranges))"""
        return ecs

    def expr_cond_pair_kernel(self, fn, direction, side, order, block):
        """This was written for creating different carpenter kernels but keeping it as it cna be used
        later
        """
        ker = Kernel(block)
        expr = fn
        ker.add_equation(expr)
        ker.set_computation_name("Carpenter scheme %s " % (fn))
        ker.set_grid_range(block)
        # modify the range to the number of points
        raise NotImplementedError("This is for testing, not implemented")
        ecs, ranges = self.expr_cond_pairs(fn, direction, side, order, block)
        ker.ranges[direction] = [ranges[0], ranges[-1]]
        return ker, ecs

    def carp4_symbols(self):
        """ Symbols for testing the 1st order one sided Carpenter wall boundary derivative.
        returns: Matrix: bc4: Matrix of stencil symbols."""
        bc4 = MatrixSymbol('BC', 4, 6)
        bc4 = Matrix(bc4)
        return bc4

    def second_der_symbols(self):
        """ Symbols for testing the 2nd order one sided Carpenter wall boundary derivative.
        returns: Matrix: bc4_2: Matrix of stencil symbols."""
        bc4_2 = MatrixSymbol('BCC', 2, 5)
        bc4_2 = Matrix(bc4_2)
        return bc4_2

    def second_der_coefficients(self):
        """ Computes the finite-difference coefficients for the 2nd order one sided Carpenter wall boundary derivative.
        returns: Matrix: bc4_2: Matrix of stencil coefficients."""
        bc4_2 = Matrix([[35.0, -104.0, 114.0, -56.0, 11.0], [11.0, -20.0, 6.0, 4.0, -1.0]])/12.0
        for i in range(bc4_2.shape[0]):
            for j in range(bc4_2.shape[1]):
                bc4_2[i, j] = nsimplify(bc4_2[i, j])
        return bc4_2

    def carp4_coefficients(self):
        """ Computes the finite-difference coefficients for the 1st order one sided Carpenter wall boundary derivative.
        returns: Matrix: bc4: Matrix of stencil coefficients."""
        R1 = -(2177.0*sqrt(295369.0)-1166427.0)/25488.0
        R2 = (66195.0*sqrt(53.0)*sqrt(5573.0)-35909375.0)/101952.0

        al4_0 = [-(216.0*R2+2160.0*R1-2125.0)/12960.0, (81.0*R2+675.0*R1+415.0)/540.0, -(72.0*R2+720.0*R1+445.0)/1440.0, -(108.0*R2+756.0*R1+421.0)/1296.0]
        al4_1 = [(81.0*R2+675.0*R1+415.0)/540.0, -(4104.0*R2+32400.0*R1+11225.0)/4320.0, (1836.0*R2+14580.0*R1+7295.0)/2160.0, -(216.0*R2+2160.0*R1+655.0)/4320.0]
        al4_2 = [-(72.0*R2+720.0*R1+445.0)/1440.0, (1836.0*R2+14580.0*R1+7295.0)/2160.0, -(4104.0*R2+32400.0*R1+12785.0)/4320.0, (81.0*R2+675.0*R1+335.0)/540.0]
        al4_3 = [-(108.0*R2+756.0*R1+421.0)/1296.0, -(216.0*R2+2160.0*R1+655.0)/4320.0, (81.0*R2+675.0*R1+335.0)/540.0, -(216.0*R2+2160.0*R1-12085.0)/12960.0]

        al4 = Matrix([al4_0, al4_1, al4_2, al4_3])

        ar4_0 = [(-1.0)/2.0, -(864.0*R2+6480.0*R1+305.0)/4320.0, (216.0*R2+1620.0*R1+725.0)/540.0, -(864.0*R2+6480.0*R1+3335.0)/4320.0, 0.0, 0.0]
        ar4_1 = [(864.0*R2+6480.0*R1+305.0)/4320.0, 0.0, -(864.0*R2+6480.0*R1+2315.0)/1440.0, (108.0*R2+810.0*R1+415.0)/270.0, 0.0, 0.0]
        ar4_2 = [-(216.0*R2+1620.0*R1+725.0)/540.0, (864.0*R2+6480.0*R1+2315.0)/1440.0, 0.0, -(864.0*R2+6480.0*R1+785.0)/4320.0, -1.0/12.0, 0.0]
        ar4_3 = [(864.0*R2+6480.0*R1+3335.0)/4320.0, -(108.0*R2+810.0*R1+415.0)/270.0, (864.0*R2+6480.0*R1+785.0)/4320.0, 0.0, 8.0/12.0, -1.0/12.0]
        ar4 = Matrix([ar4_0, ar4_1, ar4_2, ar4_3])
        # Form inverse and convert to rational
        al4_inv = al4.inv()
        bc4 = al4_inv*ar4
        # for i in range(bc4.shape[0]):
        #     for j in range(bc4.shape[1]):
        #         bc4[i, j] = nsimplify(bc4[i, j])
        return bc4


class IsothermalWallBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
    def __init__(self, boundary_direction, side, equations, const_dict, scheme=None, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_name = 'IsothermalWall'
        self.const_dict = const_dict
        self.equations = equations
        if not scheme:
            self.modification_scheme = Carpenter()
        else:
            self.modification_scheme = scheme
        return

    def apply(self, arrays, block):
        halos, kernel = self.generate_boundary_kernel(block, self.bc_name)
        n_halos = abs(halos[self.direction][self.side])
        # Using Navier Stokes physics object, create conservative variables
        NS = NSphysics(block)
        cons_vars = [NS.density(), NS.momentum(), NS.total_energy()]
        base_loc = list(cons_vars[0].indices)
        # Set wall conditions, momentum zero, rhoE specified:
        wall_eqns = [Eq(x, Float(S.Zero)) for x in NS.momentum()] + self.equations[:]
        kernel.add_equation(wall_eqns)
        # Update halos if a shock capturing scheme is being used.
        final_equations = []
        if any(isinstance(sc, ShockCapturing) for sc in block.discretisation_schemes.values()):
            # Evaluate the wall pressure
            p0, gama, Minf = GridVariable('p0'), NS.specific_heat_ratio(), NS.mach_number()
            kernel.add_equation(Eq(p0, NS.pressure(relation=True, conservative=True)))
            # Temperature evaluations for the halos
            from_side_factor, to_side_factor = self.set_side_factor()
            for i in range(1, n_halos+1):
                new_loc = base_loc[:]
                new_loc[self.direction] += to_side_factor*i
                T = self.convert_dataset_base_expr_to_datasets(NS.temperature(relation=True, conservative=True), new_loc)
                kernel.add_equation(Eq(GridVariable('T%d' % i), T))

            # Set rhoE RHS and reverse momentum components in the halos
            rhs_eqns = flatten([0, [-1*x for x in NS.momentum()], Float(S.Zero)])
            rhs_eqns[-1] = p0/(gama-1.0) + 0.5*dot(NS.momentum(), NS.momentum())/NS.density()
            # Transfer indices are the indices of halo points
            transfer_indices = [tuple([from_side_factor*t, to_side_factor*t]) for t in range(1, n_halos + 1)]

            for i, index in enumerate(transfer_indices):
                array_equations = []
                loc_lhs, loc_rhs = base_loc[:], base_loc[:]
                loc_lhs[self.direction] += index[0]
                loc_rhs[self.direction] += index[1]
                # Set rho RHS
                rhs_eqns[0] = p0*gama*Minf**2 / GridVariable('T%d' % (i+1))
                for left, right in zip(flatten(cons_vars), rhs_eqns):
                    left = self.convert_dataset_base_expr_to_datasets(left, loc_lhs)
                    right = self.convert_dataset_base_expr_to_datasets(right, loc_rhs)
                    array_equations += [Eq(left, right, evaluate=False)]
                final_equations += array_equations
        kernel.add_equation(final_equations)
        kernel.update_block_datasets(block)
        return kernel


class InletTransferBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
    """This is boundary condition should not be used until the user knows what he is doing. This is used for testing OpenSBLI"""

    def __init__(self, boundary_direction, side, equations=None, scheme=None, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_name = 'InletTransfer'
        self.equations = equations
        if not scheme:
            self.modification_scheme = Carpenter()
        else:
            self.modification_scheme = scheme
        if side != 0:
            raise ValueError("Only implemented this BC for inlet side 0.")
        return

    def apply(self, arrays, block):
        halos, kernel = self.generate_boundary_kernel(block, self.bc_name)
        cons_vars = flatten(arrays)
        equations = self.create_boundary_equations(cons_vars, cons_vars, [(0, -1)])
        kernel.add_equation(equations)
        kernel.update_block_datasets(block)
        return kernel


class InletPressureExtrapolateBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
    def __init__(self, boundary_direction, side, equations=None, scheme=None, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_name = 'InletPressureExtrapolate'
        self.equations = equations
        if not scheme:
            self.modification_scheme = Carpenter()
        else:
            self.modification_scheme = scheme
        if side != 0:
            raise ValueError("Only implemented this BC for inlet side 0.")
        return

    def apply(self, arrays, block):
        direction = self.direction
        halos, kernel = self.generate_boundary_kernel(block, self.bc_name)
        # Using Navier Stokes physics object, create conservative variables
        NS = NSphysics(block)
        cons_vars = [NS.density(), NS.momentum(), NS.total_energy()]
        # Evaluation of pressure, density, speed of sound on the boundary
        pb, rhob, ab = GridVariable('pb'), GridVariable('rhob'), GridVariable('ab')
        gama = NS.specific_heat_ratio()
        grid_vels = [GridVariable('ub%d' % i) for i in range(block.ndim)]
        grid_vels_sq = [i**2 for i in grid_vels]
        eqns = [Eq(rhob, NS.density())]
        eqns += [Eq(grid_vels[i], Abs(u/NS.density())) for i, u in enumerate(NS.momentum())]
        eqns += [Eq(pb, (gama-1)*(flatten(arrays)[-1] - 0.5*rhob*sum(flatten(grid_vels_sq))))]
        eqns += [Eq(ab, (gama*pb/rhob)**0.5)]
        kernel.add_equation(eqns)
        locations = [-1, 0]
        inlet_vel = grid_vels[direction]
        # Conditions to be set at the boundary
        for lhs in flatten(cons_vars):
            ecs = []
            rhs_values = [increment_dataset(lhs, direction, value) for value in locations]
            ecs += [ExprCondPair(rhs_values[0], GreaterThan(inlet_vel, ab))]
            ecs += [ExprCondPair(rhs_values[1], True)]
            kernel.add_equation(Eq(lhs, Piecewise(*ecs, **{'evaluate': False})))
        # Conditions set in the halos in rhoE
        locations = [-i-1 for i in range(abs(halos[0][0]))]
        lhs_rhoE = [increment_dataset(NS.total_energy(), direction, value) for value in locations]
        for i, lhs in enumerate(lhs_rhoE):
            ecs = []
            ecs += [ExprCondPair(lhs, GreaterThan(inlet_vel, ab))]  # lhs == rhs
            ecs += [ExprCondPair(NS.total_energy(), True)]
            kernel.add_equation(Eq(lhs, Piecewise(*ecs, **{'evaluate': False})))
        kernel.update_block_datasets(block)
        return kernel


class OutletTransferBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
    """This is boundary condition should not be used until the user knows what he is doing. This is used for testing OpenSBLI
    """

    def __init__(self, boundary_direction, side, equations=None, scheme=None, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_name = 'OutletTransfer'
        self.equations = equations
        if not scheme:
            self.modification_scheme = Carpenter()
        else:
            self.modification_scheme = scheme
        if side != 1:
            raise ValueError("Only implemented this BC for outlet side 1.")
        return

    def apply(self, arrays, block):
        halos, kernel = self.generate_boundary_kernel(block, self.bc_name)
        cons_vars = flatten(arrays)
        n_halos = abs(halos[self.direction][self.side])
        for i in range(n_halos+1):
            equations = self.create_boundary_equations(cons_vars, cons_vars, [(i, -1)])
            kernel.add_equation(equations)
        kernel.update_block_datasets(block)
        return kernel


class ExtrapolationBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
    """ Extrapolation boundary condition. Copies all conservative variables from 1 point inside the boundary
    to the boundary point and the halos on that side. Currently only zeroth order extrapolation."""

    def __init__(self, boundary_direction, side, order=0, equations=None, scheme=None, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_name = 'Extrapolation'
        self.equations = equations
        # Order of the extrapolation
        self.order = order
        if self.order > 0:
            raise ValueError("Only zeroth order extrapolation currently implemented.")
        if not scheme:
            self.modification_scheme = Carpenter()
        else:
            self.modification_scheme = scheme
        return

    def apply(self, arrays, block):
        halos, kernel = self.generate_boundary_kernel(block, self.bc_name)
        cons_vars = flatten(arrays)
        n_halos = abs(halos[self.direction][self.side])
        from_side_factor, to_side_factor = self.set_side_factor()
        halo_points = [0] + [from_side_factor*i for i in range(1,n_halos+1)]
        for i in halo_points:
            equations = self.create_boundary_equations(cons_vars, cons_vars, [(i, to_side_factor)])
            kernel.add_equation(equations)
        kernel.update_block_datasets(block)
        return kernel


class AdiabaticWallBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
    def __init__(self, boundary_direction, side, scheme=None, plane=True):
        BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
        self.bc_name = 'AdiabaticWall'
        if not scheme:
            self.modification_scheme = Carpenter()
        else:
            self.modification_scheme = scheme
        return

    def apply(self, arrays, block):
        halos, kernel = self.generate_boundary_kernel(block, self.bc_name)
        n_halos = abs(halos[self.direction][self.side])
        # Using Navier Stokes physics object, create conservative variables
        
        wall_eqns = []
        for ar in arrays:
            if isinstance(ar, list):
                rhs = [0 for i in range(len(ar))]
                wall_eqns += [Eq(x, y) for (x, y) in zip(ar, rhs)]
            else:
                if side == 1:
                    raise NotImplementedError("AdiabaticWall not implemented for side 1")
                # TODO increment or decrement data set value is a funciton of side factor
                wall_eqns += [Eq(ar, increment_dataset(ar, self.direction, 1))]
        kernel.add_equation(wall_eqns)
        final_equations = []
        if any(isinstance(sc, ShockCapturing) for sc in block.discretisation_schemes.values()):
            from_side_factor, to_side_factor = self.set_side_factor()
            rhs_eqns = []
            lhs_eqns = flatten(arrays)
            for ar in arrays:
                if isinstance(ar, list):
                    transformed_vector = -1*Matrix(ar)
                    rhs_eqns += flatten(transformed_vector)
                else:
                    rhs_eqns += [ar]
            transfer_indices = [tuple([from_side_factor*t, to_side_factor*t]) for t in range(1, abs(halos[self.direction][self.side]) + 1)]
            final_equations = self.create_boundary_equations(lhs_eqns, rhs_eqns, transfer_indices)
        kernel.add_equation(final_equations)
        kernel.update_block_datasets(block)
        return kernel

# class CharacteristicBoundaryConditionBlock(ModifyCentralDerivative, BoundaryConditionBase):
#     def __init__(self, boundary_direction, side, scheme = None,plane=True, Eigensystem = None):
#         BoundaryConditionBase.__init__(self, boundary_direction, side, plane)
#         if not Eigensystem:
#             raise ValueError("Needs Eigen system")
#         self.Eigensystem = Eigensystem
#         return

#     def apply(self, arrays, boundary_direction, side, block):
#         # Remove the store in weno opensbli
#         # Things in """ """ should be removed
#         """
#         self.ndim = block.ndim
#         print "in charBC"
#         pprint(self.ndim)


#         self.ev_dict = self.CS.ev_store
#         self.LEV_dict = self.CS.LEV_store
#         self.REV_dict = self.CS.REV_store

#         pprint(self.LEV_dict)
#         pprint(self.REV_dict)
#         exit()"""
#         """Explanation
#         Steps for performing characteristic boundary conditions are

#         1. Evaluate LEV as GridVariable
#         2. Evaluate lambda as grid variables
#         I think 1 and 2 you can do it
#         3. REV should be evaluated as piecewise

#         """
#         self.create_REV_conditions()
#         return

#     def create_REV_conditions(self):

#         # create REV symbolic matrix, similar to WENO
#         suffix_name = 'ChBC'
#         # Before this we need to evaluate char_bc_u, and soon
#         # convert the REV into grid variables
#         rev_in_grid =self.Eigensystem.convert_matrix_to_grid_variable(self.Eigensystem.right_eigen_vector[self.direction] ,  suffix_name)
#         # These are used as the LHS symbols for the equations
#         # rev = self.Eigensystem.generate_grid_variable_REV(self.direction, suffix_name)
#         # ev = (self.Eigensystem.eigen_value[self.direction])
#         # rev = (self.Eigensystem.right_eigen_vector[self.direction])
#         # lev = (self.Eigensystem.left_eigen_vector[self.direction])
#         # self.dQ = Matrix(symbols('dQ0:%d' % 4))
#         # v = Matrix([symbols('e0:4')])
#         # pprint(v)
#         # final = rev*ev*lev*self.dQ
#         # final4 = (final[3,:].subs(EinsteinTerm('rho'), EinsteinTerm('den')))
#         # pprint(final4[0])
#         # from opensbli.core.codegeneration import ccode
#         # print ccode(final4[0],  settings = {'rational':True})
#         # exit()
#         # pprint(rev)
#         # pprint(rev[3,:])
#         # Create the RHS, making a piecewise function, you can create an empty piecewise function but that fails while printing
#         rhs_rev = zeros(*rev.shape)
#         for i in range(rhs_rev.shape[0]):
#             for j in range(rhs_rev.shape[1]):
#                 rhs_rev[i,j] = Piecewise((rev[i,j], True))
#         # Create eigen values as local variables if required
#         ev = self.Eigensystem.generate_grid_variable_ev(self.direction, suffix_name)
#         # Create expression condition pairs, for example  let's say EV[2] <0 then zero out characteristic
#         # zero out row, CHECK this for matrix indices WARNING
#         # Making up some pairs
#         #p = (Piecewise())
#         for s in range(rhs_rev.shape[0]):
#             condition_par = list(rhs_rev[s,2].atoms(ExprCondPair)) + [ExprCondPair(0, ev[s,s] <0)]
#             rhs_rev[s,2] = Piecewise(*condition_par)
#             condition_par = list(rhs_rev[s,0].atoms(ExprCondPair)) + [ExprCondPair(1, ev[s,s] >0)]
#             rhs_rev[s,1] = Piecewise(*condition_par)
#         pprint(rhs_rev)


#         return


#     def create_conditionals(self, conditions):
#         # Get velocity to check in conditional
#         ## CHECK IF NEED ABS velocity
#         a = Symbol('a')
#         u_norm = self.ev_sym[0,0]
#         dQ = []
#         for i, REV in enumerate(conditions):
#             equations = [Eq(Symbol('dW%d' % j), eq) for j, eq in enumerate(REV*self.dW_store)]
#             dQ.append(equations)
#             pprint(dQ[-1])

#         # Side 0 inlet
#         conds_0 = Piecewise((dQ[0], And(u_norm < 0, a < u_norm)),(dQ[1], And(u_norm >= 0, a < u_norm)), (dQ[2], And(u_norm >= 0, a > u_norm)), (0 , True))
#         # Side 1 outlet
#         conds_1 = Piecewise((dQ[3], And(u_norm >= 0, a < u_norm)),(dQ[4], And(u_norm < 0, a > u_norm)), (dQ[5], And(u_norm < 0, a < u_norm)), (0 , True))

#         # Side 0 inlet
#         conds_0 = Piecewise(('condition_%d' % 0, And(u_norm < 0, a < u_norm)),('condition_%d' % 1, And(u_norm >= 0, a < u_norm)), ('condition_%d' % 2, And(u_norm >= 0, a > u_norm)), (0 , True))
#         # Side 1 outlet
#         conds_1 = Piecewise(('condition_%d' % 3, And(u_norm >= 0, a < u_norm)),('condition_%d' % 4, And(u_norm < 0, a > u_norm)), ('condition_%d' % 5, And(u_norm < 0, a < u_norm)), (0 , True))
#         pprint(conds_0)
#         pprint(conds_1)
#         return

#     def generate_derivatives(self, side, order):
#         t = self.euler_eq.time_derivative
#         Q = self.euler_eq.vector_notation.get(t)
#         dQ = zeros(self.n_ev,1)
#         wrt = self.direction

#         for i, eq in enumerate(Q):
#             func_points = self.Carpenter.generate_function_points(eq, wrt, side, char_BC=True)
#             dQ[i] = self.Carpenter.compute_derivatives(func_points, wrt, order, char_BC=True)
#         return


#     def generate_symbolic_arrays(self, direction):
#         # Create symbolic evs
#         # self.symbolic_eigen_values("ev")
#         # Store ev values and placeholders
#         self.ev = self.eigen_value[direction]
#         self.ev_sym = self.eigenvalues_symbolic
#         pprint(self.ev)
#         pprint(self.ev_sym)
#         exit()
#         self.ev_values = self.eigen_value_evaluation_eq(self.ev, "ev")
#         self.dQ = Matrix(symbols('dQ0:%d' % self.n_ev))
#         # Store LEV values and placeholders
#         self.LEV = self.left_eigen_vector[direction]
#         self.LEV_sym = self.left_eigen_vector_symbolic
#         self.LEV_values = self.left_eigen_vectors_evaluation_eq(self.LEV)
#         # Store REV values and placeholders
#         self.REV = self.right_eigen_vector[direction]
#         self.REV_sym = self.right_eigen_vector_symbolic
#         self.REV_values = self.right_eigen_vectors_evaluation_eq(self.REV)

#         dW = zeros(self.n_ev,1)
#         for i in range(self.n_ev):
#             dW[i] = self.ev_sym[i,i]*self.LEV_sym[i,:]*self.dQ
#         self.dW_store = dW
#         return

#     def zero_out_characteristics(self):
#         n_ev = self.n_ev
#         # Left cases:
#         # u_neg_lt_a: u negative, subsonic, u+a zeroed out.
#         REV = self.REV_sym.copy()
#         REV.row_del(n_ev-2)
#         m_u_neg_lt_a = REV.row_insert(n_ev-2, zeros(1, n_ev))
#         # u_pos_lt_a: u positive, subsonic, u, u, u, u+a zeroed out.
#         REV = self.REV_sym.copy()
#         m_u_pos_lt_a = zeros(n_ev-1, n_ev)
#         m_u_pos_lt_a = m_u_pos_lt_a.row_insert(n_ev-1, REV[n_ev-1, :])
#         # u_pos_gt_a: u positive, supersonic, u, u, u, u+a, u-a zeroed out.
#         m_u_pos_gt_a = zeros(n_ev, n_ev)

#         # Right cases:
#         # u_pos_lt_a: u positive, subsonic, u-a zeroed out.
#         REV = self.REV_sym.copy()
#         REV.row_del(n_ev-1)
#         p_u_pos_lt_a = REV.row_insert(n_ev-1, zeros(1,n_ev))
#         # u_neg_gt_a: u negative, supersonic, u, u, u, u+a, u-a zeroed out.
#         p_u_neg_gt_a = zeros(n_ev, n_ev)
#         # u_neg_lt_a : u negative, subsonic, u, u, u, u+a zeroed out.
#         REV = self.REV_sym.copy()
#         p_u_neg_lt_a = zeros(n_ev-1, n_ev)
#         p_u_neg_lt_a = p_u_neg_lt_a.row_insert(n_ev-2, REV[n_ev-1, :])
#         conditions = [m_u_neg_lt_a, m_u_pos_lt_a, m_u_pos_gt_a, p_u_pos_lt_a, p_u_neg_gt_a, p_u_neg_lt_a]

#         return conditions


#     def return_to_conservative(self):
#         self.Q = self.REV*self.W
#         pprint(self.Q)
#         pprint(self.REV)
#         return

#     def test_eigvalues(self, ev, ndim):
#         if ndim == 1:
#             subs_list = {Symbol('a'): 3.5 ,Symbol('u0'): -0.5}
#         elif ndim == 2:
#             subs_list = {Symbol('a'): 3.5, Symbol('u0'): -0.5, Symbol('u1'): -0.25}
#         elif ndim == 3:
#             subs_list = {Symbol('a'): 3.5, Symbol('u0'): -0.5, Symbol('u1'): -0.25, Symbol('u2'): -0.05}

#         g = lambda x:x.subs(subs_list, evaluate=False)
#         return ev.applyfunc(g)
#     def evaluate_derivatives(self, direction):
#         t = self.euler_eq.time_derivative
#         Q = Matrix(self.euler_eq.vector_notation.get(t))
#         F = Matrix(self.euler_eq.vector_notation.get(direction))
#         dQ = Q.diff(direction)
#         dF = F.diff(direction)
#         pprint(dQ)
#         pprint(dF)
#         return
