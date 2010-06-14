# -*- coding: utf-8 -*-
#'django-cube'
#Copyright (C) 2010 Sébastien Piquemal @ futurice
#contact : sebastien.piquemal@futurice.com
#futurice's website : www.futurice.com

#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.

#You should have received a copy of the GNU General Public License
#along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
"""
from collections import MutableMapping
import re
import copy
from datetime import date, datetime

from django.core.exceptions import FieldError
from django.db.models import ForeignKey
from django.db.models.sql import constants

from collections import defaultdict

class Cube(MutableMapping):
    """
    A cube that can calculate lists of measures for a queryset, on several dimensions.
    """
    def __init__(self, dimensions, queryset, aggregation, constraint={}, sample_space={}):
        """
        """
        self.sample_space = sample_space
        self.constraint = constraint
        self.dimensions = self._to_dimensions(dimensions)
        self.aggregation = aggregation
            
    def iteritems(self):
        """
        Iterates on the items (*coordinate*, *measure*), where *coordinate* is a :class:`Coords` object, and *measure* is the value of the aggregation at *coordinate* position. There is one item for each coordinates in the cube's sample space.
        """
        #To cover the whole cube's sample space, we will :
        #1- pick one of the cube's dimensions
        #2- constrain it with every possible value, and calculate a subcube for each constraint
        #3- merge the coordinates of subcubes' measures with the constraint value, in order to get the complete coordinates of the measure

        free_dimensions = [self.dimensions[name] for name in set(self.dimensions) - set(self.constraint)]

        #If there are free dimensions, we need to calculate subcubes and merge the results.
        if len(free_dimensions):
            #we fix a dimension,
            fixed_dimension = free_dimensions.pop()
            #and create a subcube with the remaining free dimensions,
            #one for each value in the fixed dimension's sample space.
            #Every one of these cubes is constrained *fixed_dimension=value*
            sample_space = self.get_sample_space(fixed_dimension.name)
            sorted_sample_space = self._sort_sample_space(sample_space)
            for value in sorted_sample_space:
                #subcube_constraint = cube_constraint + extra_constraint
                extra_constraint = {fixed_dimension.name: value}
                #constrained subcube
                subcube = self.constrain(extra_constraint)
                subcube_constraint = copy.copy(subcube.constraint)
                #we yield all the measures for the constrained cube
                for coords, measure in subcube.iteritems():
                    merged_constraint = copy.copy(subcube_constraint)
                    merged_constraint.update(coords)
                    merged_coords = Coords(**merged_constraint)
                    yield (merged_coords, measure)
            raise StopIteration

        #There is no free dimension, so we can yield the measure.
        else:
            yield (Coords(), self._measure())
            raise StopIteration

    def subcube(self, dimensions=None, extra_constraint={}):
        """
        :returns: Cube -- a subcube of the calling cube, whose dimensions are *dimensions*, and which is constrained with *extra_constraint*. 

        :param dimensions: list -- a subset of the calling cube's dimensions namees. If *dimensions* is not provided, it defaults to the calling cube's.
        :param extra_constraint: dict -- a dictionnary of constraint *{dimension_name: value}*. Constrained dimensions must belong to the subcube's dimensions.
        
        :raise: ValueError -- if a dimension passed along *dimensions* is not a dimension of the calling cube, or if a dimension constrained in *extra_constraint* is not a dimension of the returned subcube.
        """
        #default value for *constraint*
        constraint = copy.copy(self.constraint)
        #default value for *dimensions*
        if dimensions == None:
            dimensions = self.dimensions
        #building the new cube's *constraint*
        else:
            dimensions = self._to_dimensions(dimensions)
            constraint = copy.copy(self.constraint)
            #if some dimensions are deleted, we delete also the constraints
            for dimension in (set(self.dimensions) - set(dimensions)):
                try:
                    constraint.pop(dimension)
                except KeyError:
                    pass
            constraint.update(extra_constraint)

        if not set(extra_constraint) <= set(dimensions):
            raise ValueError('%s is(are) not valid constraint dimension(s) for this cube' % (set(constraint.keys()) - dimensions))
        elif not dimensions <= self.dimensions:
            raise ValueError('%s is(are) not dimension(s) of the cube' % (dimensions - self.dimensions))
        else:
            cube_copy = copy.copy(self)
            cube_copy.dimensions = dimensions
            cube_copy.constraint = constraint
            return cube_copy
     
    def constrain(self, extra_constraint):
        """
        Merges the calling cube's constraint with *extra_constraint*.

        :returns: Cube -- a subcube of the calling cube. 
        """
        constraint = copy.copy(self.constraint)
        constraint.update(extra_constraint)
        cube_copy = copy.copy(self)
        cube_copy.constraint = constraint
        return cube_copy

    def resample(self, dimension, lower_bound=None, upper_bound=None, space=None):
        """
        Returns a copy of the calling cube, whose sample space of *dimension* is limited to : ::

            *space* INTER [*lower_bound*, *upper_bound*]

        If *space* is not defined, the sample space of the calling cube's *dimension* is taken instead.
        """
        #calculate dimension's new sample space
        new_space = space or dimension.get_sample_space(dimension)
        lower_bound = lower_bound or min(new_space)
        upper_bound = upper_bound or max(new_space)
        new_space = filter(lambda elem: elem >= lower_bound and elem <= upper_bound, new_space)
        #calculate cube's new sample space
        cube_space = copy.copy(self.sample_space)
        cube_space.update({dimension: new_space})        

        cube_copy = copy.copy(self)
        cube_copy.sample_space = cube_space
        return cube_copy

    def measure(self):
        """
        Returns the measure calculated on the whole cube, takes no account of the cube's dimensions.
        """
        return self.subcube([])[Coords()]

    def _measure(self):
        """
        Calculates and returns the measure on the cube.
        """
        raise NotImplementedError

    def _sort_sample_space(self, sspace):
        """
        :param sspace: the sample space to sort, can be any iterable
        :returns: list -- the sample space sorted
        """
        return sorted(list(sspace))

    @staticmethod
    def _to_dimensions(composite_list):
        """
        Takes a list of both :class:`Dimension` objects and string, and returns a set of :class:`Dimension` objects. 
        """
        dimensions = dict()
        for dimension in composite_list:
            if isinstance(dimension, str):
                dimensions[dimension] = Dimension(dimension)
            elif isinstance(dimension, Dimension):
                dimensions[dimension] = copy.copy(dimension)
            else:
                raise TypeError('\'%s\' of type %s is not an appropriate dimension for a cube' % (dimension, type(dimension)))
        return dimensions

    def __copy__(self):
        """
        Returns a shallow copy of the cube.
        """
        dimensions = copy.copy(self.dimensions)
        queryset = copy.copy(self.queryset)
        sample_space = copy.copy(self.sample_space)
        constraint = copy.copy(self.constraint)
        aggregation = self.aggregation
        return BaseCube(dimensions, queryset, aggregation, constraint=constraint, sample_space=sample_space)

    def __repr__(self):
        dim_str = ''
        for dim in self.dimensions:
            if self.constraint.get(dim):
                dim_str += dim + '=' + str(self.constraint[dim]) + ', '
            else:
                dim_str += dim + ', '
        return 'Cube(%s)' % dim_str[:-2]
    
    def __getitem__(self, coordinates):
        """
        Returns the measure at *coordinates*
        """
        return dict(self.iteritems())[coordinates]

    def __len__(self):
        """
        Returns the length of the sample space
        """
        return len(dict(self.iteritems()))
    
    def __iter__(self):
        """
        Iterates on the whole sample space
        """
        return iter(dimension for dimension, measure in self.iteritems())
    
    def __contains__(self, coordinates):
        """
        Returns True if *coordinates* belongs to the cube.
        """
        return coordinates in dict(self.iteritems())
    
    def __delitem__(self, key):
        raise NotImplementedError
    
    def __setitem__(self, key, value):
        raise NotImplementedError


class BaseDimension(object):
    
    def __init__(self, field, queryset=None, name=None, sample_space=None):
        self.field = field
        self.name = name or field
        self.sample_space = sample_space or set()
    
    def __hash__(self):
        return self.name.__hash__()
    
    def __copy__(self):
        return Dimension(self.field, self.name, self.sample_space)
    
    def __eq__(self, other):
        if isinstance(other, Dimension):
            return self.name == other.name
        elif isinstance(other, str):
            return self.name == other
        else:
            raise TypeError("Cannot compare dimension to %s" % type(other))

    def __repr__(self):
        return "Dimension(%s)" % self.name
        

class Coords(MutableMapping):
    def __init__(self, **kwargs):
        self._dimensions = kwargs.keys()
        for dimension, value in kwargs.iteritems():
            setattr(self, dimension, value)

    def __hash__(self):
        self._dimensions.sort()
        hash_key = ''
        for dimension in self._dimensions:
            hash_key += dimension + '=' + str(getattr(self, dimension))
        return hash(hash_key)
    
    def __repr__(self):
        self._dimensions.sort()
        coord_str = ''
        for dimension in self._dimensions:
            coord_str += dimension + '=' + repr(getattr(self, dimension)) + ', '  
        return 'Coords(%s)' % coord_str[:-2]
    
    def __setitem__(self, key, value):
        if not key in self._dimensions:
            raise KeyError('%s is not a valid dimension' % key)
        else:
            setattr(self, key, value)
    
    def __getitem__(self, key):
        if not key in self._dimensions:
            raise KeyError('%s is not a valid dimension' % key)
        else:
            return getattr(self, key)

    def __len__(self):
        return len(self._dimensions)
    
    def __iter__(self):
        return iter(self._dimensions)
    
    def __contains__(self, key):
        return key in self._dimensions
    
    def __delitem__(self, key):
        raise NotImplementedError
    
        
        
