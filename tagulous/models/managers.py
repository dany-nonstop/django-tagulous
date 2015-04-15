"""
Tagulous model field managers

These are accessed via the descriptors, and do the work of storing and loading
the tags.
"""

from django.core import exceptions

from tagulous.utils import parse_tags, render_tags


###############################################################################
####### Base class for tag field managers
###############################################################################

class BaseTagManager(object):
    """
    Base class for SingleTagManager and RelatedManagerTagMixin
    """
    def __eq__(self, other):
        """
        Treat the other value as a string and compare to tags
        """
        other_str = u"%s" % other
        
        # Enforce case non-sensitivity or lowercase
        lower = False
        if self.tag_options.force_lowercase or not self.tag_options.case_sensitive:
            lower = True
            other_str = other_str.lower()
        
        # Parse other_str into list of tags
        other_tags = parse_tags(other_str)
        
        # Get list of set tags
        self_tags = self.get_tag_list()
        
        # Compare tag count
        if len(other_tags) != len(self_tags):
            return False
        
        # ++ Could optimise comparison for lots of tags by using an object
        
        # Compare tags
        for tag in self_tags:
            # If lowercase or not case sensitive, lower for comparison
            if lower:
                tag = tag.lower()
            
            # Check tag in other tags
            if tag not in other_tags:
                return False
        
        # Same number of tags, and all self tags present in other tags
        # It's a match
        return True
        
    def __ne__(self, other):
        return not self.__eq__(other)
        

###############################################################################
####### Manager for SingleTagField
###############################################################################

class SingleTagManager(BaseTagManager):
    """
    Manage single tags
    
    Not a real Django manager; it's a per-instance abstraction between the
    normal FK descriptor to hold in-memory changes of the SingleTagField before
    passing them up to the normal FK descriptor on the pre-save signal.
    """
    def __init__(self, descriptor, instance):
        # The SingleTagDescriptor and instance this manages
        self.descriptor = descriptor
        self.instance = instance
        
        # Other vars we need
        self.tag_model = self.descriptor.tag_model
        self.field = self.descriptor.field
        self.tag_options = self.descriptor.tag_options
        
        # Keep track of unsaved changes
        self.changed = False
        
        # The descriptor stores an unsaved tag string
        # Load the actual value into the cache, if it exists
        self.tag_cache = self.get_actual()
        
        # Start off the local tag name with the actual tag name
        self.tag_name = self.tag_cache.name if self.tag_cache else None
        
        # Pre/post save will need to keep track of an old tag
        self.removed_tag = None
        
    def flush_actual(self):
        """
        Clear the FK descriptor's cache
        """
        # Flush the cache of actual
        cache_name = self.field.get_cache_name()
        if hasattr(self.instance, cache_name):
            delattr(self.instance, cache_name)
        
    def get_actual(self):
        """
        Get the actual value of the instance according to the FK descriptor
        """
        # A ForeignKey would be on the .attname (field_id), but only
        # if it has been set, otherwise the attribute will not exist
        if hasattr(self.instance, self.field.attname):
            return self.descriptor.descriptor.__get__(self.instance)
        return None
    
    def set_actual(self, value):
        """
        Set the actual value of the instance for the FK descriptor
        """
        return self.descriptor.descriptor.__set__(self.instance, value)
        
    def get_tag_string(self):
        """
        Get the tag edit string for this instance as a string
        """
        if not self.instance:
            raise AttributeError("Function get_tag_string is only accessible via an instance")
        
        return render_tags( self.get() )
    
    def get_tag_list(self):
        """
        Get the tag names for this instance as a list of tag names
        """
        if not self.instance:
            raise AttributeError("Function get_tag_list is only accessible via an instance")
        
        return [tag.name for tag in self.get() ]
        
    def get(self):
        """
        Get the current tag - either a Tag object or None
        If the field has been changed since the instance was last saved, the
        Tag object may be a dynamically generated Tag which does not exist in
        the database yet. The count will not be updated until the instance is
        next saved.
        """
        # If changed, find the tag
        if self.changed:
            if not self.tag_name:
                return None
            
            # Try to look up the tag
            try:
                if self.tag_options.case_sensitive:
                    tag = self.tag_model.objects.get(name=self.tag_name)
                else:
                    tag = self.tag_model.objects.get(name__iexact=self.tag_name)
            except self.tag_model.DoesNotExist:
                # Does not exist yet, create a temporary one (but don't save)
                if not self.tag_cache:
                    self.tag_cache = self.tag_model(name=self.tag_name, protected=False)
                tag = self.tag_cache
            return tag
        else:
            # Return the response that it should have had (a Tag or None)
            return self.get_actual()
        
    def set(self, value):
        """
        Set the current tag
        """
        # Parse a tag string
        if not value:
            tag_name = ''
            
        elif isinstance(value, basestring):
            # Force tag to lowercase
            if self.tag_options.force_lowercase:
                value = value.lower()
                
            # Remove quotes from value to ensure it's a valid tag string
            tag_name = value.replace('"', '') or None
            
        # Look up the tag name
        else:
            tag_name = value.name
        
        # If no change, do nothing
        if self.tag_name == tag_name:
            return
        
        # Store the tag name and mark changed
        self.changed = True
        self.tag_name = tag_name
        self.tag_cache = None
        
    def pre_save_handler(self):
        """
        When the model is about to save, update the tag value
        """
        # Get the new tag
        new_tag = self.get()
        
        # Logic check to replace standard null/blank model field validation
        if not new_tag and self.field.required:
            raise exceptions.ValidationError(self.field.error_messages['null'])
        
        # Only need to go further if there has been a change
        if not self.changed:
            return
        
        # Store the old tag so we know to decrement it in post_save
        self.flush_actual()
        self.removed_tag = self.get_actual()
        
        # Create or increment the tag object
        if new_tag:
            # Ensure it is in the database
            if not new_tag.pk:
                new_tag.save()
                
            # Increment the new tag
            new_tag.increment()
        
        # Set it
        self.set_actual(new_tag)
        
        # Clear up
        self.changed = False
        
    def post_save_handler(self):
        """
        When the model has saved, decrement the old tag
        """
        if self.removed_tag:
            self.removed_tag.decrement()
    
    def post_delete_handler(self):
        """
        When the model has been deleted, decrement the actual tag
        """
        # Decrement the actual tag
        self.flush_actual()
        old_tag = self.get_actual()
        if old_tag:
            old_tag.decrement()
            self.set_actual(None)
            
            # If there is no new value, mark the old one as a new one,
            # so the database will be updated if the instance is saved again
            if not self.changed:
                self.tag_name = old_tag.name
            self.tag_cache = None
            self.changed = True
        

###############################################################################
####### Mixin for TagField manager
###############################################################################
        
class RelatedManagerTagMixin(BaseTagManager):
    """
    Mixin for RelatedManager to add tag functions
    
    Added to the normal m2m RelatedManager, after it has been instantiated.
    This holds in-memory changes of the TagField before committing them to the
    database on the post-save signal.
    """
    def __init_tagulous__(self, descriptor):
        """
        Called directly after the mixin is added to the instantiated manager
        """
        self.tag_model = descriptor.tag_model
        self.tag_options = descriptor.tag_options
        
        # Maintain an internal set of tags, and track whether they've changed
        # If internal tags are None, haven't been loaded yet
        self.changed = False
        self.tags = None
        self.reload()
    
    def reload(self):
        """
        Get the actual tags
        """
        # Convert to a list to force it to load now, and so we can change it
        self.tags = list(self.all())
        self.changed = False
    
    def save(self, force=False):
        """
        Set the actual tags to the internal tag state
        
        If force is True, save whether we think it has changed or not
        """
        if not self.changed and not force:
            return
        
        # Add and remove tags as necessary
        new_tags = self._ensure_tags_db(self.tags)
        self.reload()
        # Add new tags
        for new_tag in new_tags:
            if new_tag not in self.tags:
                self.add(new_tag)
        
        # Remove old tags
        for old_tag in self.tags:
            if old_tag not in new_tags:
                self.remove(old_tag)
        self.tags = new_tags
        self.changed = False
    
    def _ensure_tags_db(self, tags):
        """
        Ensure that self.tags all exist in the database
        """
        db_tags = []
        for tag in tags:
            if tag.pk:
                # Already in DB
                db_tag = tag
            else:
                # Not in DB - get or create
                try:
                    if self.tag_options.case_sensitive:
                        db_tag = self.tag_model.objects.get(name=tag.name)
                    else:
                        db_tag = self.tag_model.objects.get(name__iexact=tag.name)
                except self.tag_model.DoesNotExist:
                    db_tag = self.tag_model.objects.create(
                        name=tag.name, protected=False,
                    )
            db_tags.append(db_tag)
        return db_tags
    
    #
    # New add, remove and clear, to update tag counts
    # Will be switched into place by TagDescriptor
    #
    def _add(self, *objs):
        # Convert strings to tag objects
        new_tags = []
        for tag in objs:
            if isinstance(tag, basestring):
                new_tags.append(self.tag_model.objects.create(name=tag))
            else:
                new_tags.append(tag)
        
        # Don't trust the internal tag cache
        self.reload()
        
        # Enforce max_count
        if self.tag_options.max_count:
            current_count = len(self.tags)
            if current_count + len(new_tags) > self.tag_options.max_count:
                raise ValueError(
                    "Cannot set more than %s tags on this field; it already has %s" % (
                        self.tag_options.max_count, current_count,
                    )
                )
        
        # Add to db, add to cache, and increment
        self._old_add(*self._ensure_tags_db(new_tags))
        for tag in new_tags:
            self.tags.append(tag)
            tag.increment()
    _add.alters_data = True
    
    def _remove(self, *objs):
        # Convert strings to tag objects - if object doesn't exist, skip
        rm_tags = []
        for tag in objs:
            if isinstance(tag, basestring):
                try:
                    rm_tags.append(self.tag_model.objects.get(name=tag))
                except self.tag_model.DoesNotExist:
                    continue
            else:
                rm_tags.append(tag)
        
        # Don't trust the internal tag cache
        self.reload()
        
        # Cut tags back to only ones already set
        rm_tags = [
            tag for tag in self.tags if tag in rm_tags
        ]
        
        # Remove from cache
        self.tags = [tag for tag in self.tags if tag not in rm_tags]
        
        # Remove from db and decrement
        self._old_remove(*self._ensure_tags_db(rm_tags))
        for tag in rm_tags:
            tag.decrement()
        
    _remove.alters_data = True

    def _clear(self):
        # Don't trust the internal tag cache
        self.reload()
        
        # Clear db, then decrement and empty cache
        self._old_clear()
        for tag in self.tags:
            tag.decrement()
        self.tags = []
    _clear.alters_data = True
    
        
    #
    # Functions for getting and setting tags
    #
    
    def get_tag_string(self):
        """
        Get the tag edit string for this instance as a string
        """
        if not self.instance:
            raise AttributeError("Method is only accessible via an instance")
        
        return render_tags(self.tags)
    
    def get_tag_list(self):
        """
        Get the tag names for this instance as a list of tag names
        """
        # ++ Better as get_tag_strings?
        if not self.instance:
            raise AttributeError("Method is only accessible via an instance")
        
        return [tag.name for tag in self.tags]
        
    def set_tag_string(self, tag_string):
        """
        Sets the tags for this instance, given a tag edit string
        """
        if not self.instance:
            raise AttributeError("Method is only accessible via an instance")
        
        # Get all tag names
        tag_names = parse_tags(tag_string)
        
        # Pass on to set_tag_list
        return self.set_tag_list(tag_names)
    set_tag_string.alters_data = True
        
    def set_tag_list(self, tag_names):
        """
        Sets the tags for this instance, given a list of tag names
        """
        if not self.instance:
            raise AttributeError("Method is only accessible via an instance")
        
        if self.tag_options.max_count and len(tag_names) > self.tag_options.max_count:
            raise ValueError("Cannot set more than %d tags on this field" % self.tag_options.max_count)
        
        # Force tag_names to unicode strings, just in case
        tag_names = [u'%s' % tag_name for tag_name in tag_names]
        
        # Apply force_lowercase
        if self.tag_options.force_lowercase:
            # Will be lowercase for later comparison
            tag_names = [name.lower() for name in tag_names]
        
        # Prep tag lookup
        # old_tags      = { cmp_name: tag }
        # cmp_new_names = { cmp_name: cased_name }
        if self.tag_options.case_sensitive:
            old_tags = dict(
                [(tag.name, tag) for tag in self.tags]
            )
            cmp_new_names = dict([(n, n) for n in tag_names])
        else:
            # Not case sensitive - need to compare on lowercase
            old_tags = dict(
                [(tag.name.lower(), tag) for tag in self.tags]
            )
            cmp_new_names = dict(
                [(name.lower(), name) for name in tag_names]
            )
        
        # See which tags are staying
        new_tags = []
        for cmp_old_name, old_tag in old_tags.items():
            if cmp_old_name in cmp_new_names:
                # Exists - add to new tags
                new_tags.append(old_tag)
                del cmp_new_names[cmp_old_name]
            else:
                # Tag will be removed
                self.changed = True
        
        # Only left with tag names which aren't present
        for tag_name in cmp_new_names.values():
            # Find or create all new tags
            try:
                if self.tag_options.case_sensitive:
                    tag = self.tag_model.objects.get(name=tag_name)
                else:
                    tag = self.tag_model.objects.get(name__iexact=tag_name)
            except self.tag_model.DoesNotExist:
                # Don't create it until it's saved
                tag = self.tag_model(name=tag_name, protected=False)
                
            # Add the tag
            new_tags.append(tag)
            self.changed = True
        
        # Store in internal tag cache
        self.tags = new_tags
    # ++ Is this still true?
    set_tag_list.alters_data = True
    
    def __unicode__(self):
        """
        If called on an instance, return the tag string
        """
        if hasattr(self, 'instance'):
            return self.get_tag_string()
        else:
            return super(RelatedManagerTagMixin, self).__str__()
            
    def __str__(self):
        return unicode(self).encode('utf-8')
