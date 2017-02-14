#!/usr/bin/env python

#    OpenSBLI: An automatic code generator for solving differential equations.
#    Copyright (C) 2016 Satya P. Jammy and others

#    This file is part of OpenSBLI.

#    OpenSBLI is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    OpenSBLI is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

#    You should have received a copy of the GNU General Public License
#    along with OpenSBLI.  If not, see <http://www.gnu.org/licenses/>

# @author: New structure implemented by Satya P Jammy (October, 2016)

from .grid import *
from sympy.matrices import *
from .bcs import BoundaryConditionTypes
from .opensbliequations import SimulationEquations
from .opensbliobjects import ConstantObject, DataObject, DataSetBase
#from .opensbliobjects import 
from sympy import flatten
class DataSetsToDeclare(object):
    datasetbases = []
class KernelCounter():
    # Counter for the kernels
    def __init__(self):
        self.kernel_counter = 0

    def reset_kernel_counter(self):
        self.kernel_counter = 0
        return
    @property
    def increase_kernel_counter(self):
        self.kernel_counter = self.kernel_counter +1
        return

    def store_kernel_counter(self):
        self.stored_counter = self.kernel_counter
        return

    def reset_kernel_to_stored(self):
        self.kernel_counter = self.stored_counter
        return

class RationalCounter():
    # Counter for the kernels
    def __init__(self):
        self.name = 'rc%d'
        self.rational_counter = 0
    @property
    def increase_rational_counter(self):
        self.rational_counter = self.rational_counter +1
        return
    @property
    def get_next_rational_constant(self):
        name = self.name % self.rational_counter
        self.increase_rational_counter
        ret = ConstantObject(name)
        return ret
class SimulationBlock(Grid, KernelCounter, BoundaryConditionTypes, RationalCounter): # BoundaryConditionTypes add this later
    def __init__(self, ndim, block_number = None):
        if block_number:
            self.blocknumber = block_number
        else:
            self.blocknumber = 0
        self.ndim = ndim
        KernelCounter.__init__(self)
        Grid.__init__(self)
        RationalCounter.__init__(self)
        self.boundary_halos = [[set(), set()] for d in range(self.ndim)]
        self.block_datasets = {}
        self.constants = {}
        self.Rational_constants = {}
        self.block_stencils = {}
        DataSetBase.block = self
        return

    @property
    def blockname(self):
        return 'OpenSBLIBlock%d' % self.blocknumber

    def set_block_number(self, number):
        self.blocknumber = number
        return

    def set_block_boundaries(self, bclist):
        self.set_boundary_types(bclist)

    def set_block_boundary_halos(self, direction, side, types):
        self.boundary_halos[direction][side].add(types)
        return
    
    def dataobjects_to_datasets_on_block(self, eqs):
        all_equations = flatten(eqs)[:]
        
        from sympy import *
        for no, eq in enumerate(all_equations):
            for d in eq.atoms(DataObject):
                new = DataSetBase(d)[[0 for i in range(self.ndim)]]
                eq = eq.subs({d: new})
            all_equations[no] = eq
        # Convert all equations into the format of input equations WARNING crude way
        out = []
        out_loc = 0
        for no, e in enumerate(eqs):
            if isinstance(e, list):
                out += [all_equations[out_loc:out_loc+len(e)]]
                out_loc += len(e)
            else:
                out += [all_equations[out_loc]]
                out_loc += 1
        return out
    
    def discretise(self):
        """
        In this the discretisation of the schemes in the list of equations is applied
        :arg list_of_equations: a list of the type of equations (simulation equations, Constituent relations,
        Metric equations, diagnostic equations etc)
        : ar
        """
        # set the block for the data sets
        DataSetBase.block = self
        # Convert the equations into block datasets
        for eq in self.list_of_equation_classes:
            block_eq = self.dataobjects_to_datasets_on_block(eq.equations)
            eq.equations = block_eq
        
        # perform the spatial discretisation of the equations using schemes
        for eq in self.list_of_equation_classes:
            eq.spatial_discretisation(self.discretisation_schemes, self)
            eq.apply_boundary_conditions(self)
        # Get the classes for the constituent relations
        crs = self.get_constituent_equation_class
        #for clas in self.list_of_equation_classes:
            #if clas not in crs:
                #print clas, "Exitting"
                #exit()
        # perform the temporal discretisation of the equations for all equation classes
        # Later move TD to equations.td
        temporal = self.get_temporal_schemes
        for t in temporal:
            for eq in self.list_of_equation_classes:
                self.discretisation_schemes[t.name].discretise(eq, self)
        return

    def apply_boundary_conditions(self, arrays):
        kernels = []
        for no,b in enumerate(self.boundary_types):
            kernels += [self.apply_bc_direction(no, 0, arrays)]
            kernels += [self.apply_bc_direction(no, 1, arrays)]
        return kernels

    def apply_bc_direction(self, direction, side, arrays):
        kernel = self.boundary_types[direction][side].apply(arrays, direction, side, self)
        return kernel

    def set_equations(self, list_of_equations):
        self.list_of_equation_classes = list_of_equations
        return

    def set_discretisation_schemes(self, schemes):
        self.discretisation_schemes = schemes
        return

    @property
    def get_constituent_equation_class(self):
        from .opensbliequations import ConstituentRelations as CR
        CR_classes = []
        for sc in self.list_of_equation_classes:
            if isinstance(sc, CR):
                CR_classes += [sc]
        return CR_classes

    @property
    def get_temporal_schemes(self):
        temporal = []
        for sc in  self.discretisation_schemes:
            if self.discretisation_schemes[sc].schemetype == "Temporal":
                temporal += [self.discretisation_schemes[sc]]
        return temporal
    @property
    def collect_all_spatial_kernels(self):
        all_kernels = []
        for scheme in self.get_temporal_schemes:
            for key, value in scheme.solution.iteritems(): # These are equation classes
                if key.order >=0 and key.order <100: #Checks if the equation classes are part of the time loop
                    all_kernels += key.all_spatial_kernels
                else:
                    print 'NOPE' # Just checking
        return all_kernels

    def grid_generation(self):

        return

    def initial_conditions(self):

        return

    def io(self):
        return

    def pre_process_eq(self, eq_class):
        """
        These are type non Simulation equations
        """
        return

    def post_process_eq(self, eq_class_list):

        return

def sort_constants(constants_dictionary):
    known_constants, unknown_constants = [], []
    pprint(constants_dictionary)
    for const in constants_dictionary.values():
        if const.is_input:
            known_constants.append(const)
        else:
            unknown_constants.append(const)
    while len(unknown_constants) != 0:
        set_of_known = set(known_constants)
        for const in unknown_constants:
            requires = const.value.atoms(ConstantObject)
            if requires.issubset(set_of_known):
                print "const: ", const, " has formula: ", const.value, " requires: ", requires
                known_constants.append(const)
                unknown_constants = [x for x in unknown_constants if not const]
            else:
                print const, "is missing", " it requires", requires
    return known_constants